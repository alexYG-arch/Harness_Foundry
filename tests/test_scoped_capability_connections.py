"""Cross-entry regression cases for the versioned connection selection."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import builtins
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tests.test_capability_connections import load

P, C, D, U = [load(n) for n in ('prepare', 'connections', 'delivery', 'upgrade')]
A, B = 'instance.alpha', 'project.beta'


def read_json(path):
    return json.loads(path.read_bytes())


@contextmanager
def accesses():
    """Observe attempted access, including errors swallowed by the loader."""
    paths = []
    def record(fn):
        def wrapped(path, *args, **kwargs):
            if isinstance(path, (str, os.PathLike)):
                paths.append(os.path.abspath(path))
            return fn(path, *args, **kwargs)
        return wrapped
    with ExitStack() as stack:
        for module, name in [(io, 'open'), (builtins, 'open'), (os, 'open'), (os, 'stat'),
                             (os, 'lstat'), (os, 'readlink'), (os, 'scandir'), (os, 'listdir')]:
            stack.enter_context(patch.object(module, name, record(getattr(module, name))))
        yield paths


class ScopedConnectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.instance = self.root / 'instance'
        self.project = self.root / 'project'
        self.instance.mkdir()
        self.project.mkdir()
        self.alpha = self.package('alpha')
        self.beta = self.package('beta')
        C.configure(self.instance, 'instance', 'alpha', self.alpha, ['base.md'])
        C.configure(self.project, 'project', 'beta', self.beta, ['base.md'])
        (self.project / 'brief.md').write_text('Project brief.\n')
        self.base = {'source_manifest': [{'source_id': 'BRIEF', 'path': 'brief.md'}],
                     'request': {'requirement_ir': {'sources': [{'source_id': 'BRIEF', 'path_or_uri': 'brief.md'}]},
                                 'plan': {'workpacks': [{'workpack_id': k, 'inputs': [{'kind': 'SOURCE', 'id': 'BRIEF'}]}
                                                        for k in ('MAKE', 'DOCS')]}},
                     'scope': {'max_attempts': 3}}
        self.cfg = {'connections': {'selection_version': 1, 'build': [], 'target': [],
                                     'instance_root': str(self.instance), 'workpack_ids': ['MAKE']},
                    'selections': [], 'project_root': str(self.project), 'base_materials': self.base,
                    'source_root': str(self.project)}
        self.builtin = self.root / 'builtin'
        self.builtin.mkdir()
        (self.builtin / 'capability.json').write_text(json.dumps({'name': 'local', 'version': '1', 'usage': 'both',
                'inputs': ['project'], 'outputs': ['guide'], 'materials': ['guide.md']}))
        (self.builtin / 'guide.md').write_text('Local project check.\n')
        self.local = {'directory': str(self.builtin), 'version': '1', 'workpack_ids': ['MAKE']}

    def package(self, provider):
        package = self.root / provider
        (package / '.cursor-plugin').mkdir(parents=True)
        (package / '.cursor-plugin/plugin.json').write_text(json.dumps({'name': provider, 'version': '1', 'skills': 'skills'}))
        for name in ('review', 'spare', 'reference'):
            path = package / 'skills' / name / 'SKILL.md'
            path.parent.mkdir(parents=True)
            path.write_text(f'---\nname: {name}\ndescription: Read {name}\n---\n{provider}-{name}-BODY\n')
        (package / 'base.md').write_text(provider + '-base')
        (package / 'LICENSE').write_text(provider + ' license')
        return package

    def config(self, build=(), target=()):
        conf = deepcopy(self.cfg)
        conf['connections'].update(build=list(build), target=list(target))
        return conf

    def legacy(self):
        conf = self.config()
        for k in ('selection_version', 'build', 'target'):
            del conf['connections'][k]
        return conf

    def write(self, conf, name):
        return P.write_materials(conf, self.root / name)

    def assertUntouched(self, paths, *roots):
        for root in roots:
            self.assertFalse(any(p == str(root) or p.startswith(str(root) + '/') for p in paths), root)

    def test_P1_explicit_empty(self):
        old = self.write(self.legacy(), 'old')
        self.assertEqual(len(old['preparation']['external_connections']), 2)
        for n, selections in enumerate(([], [self.local])):
            cfg = self.config()
            cfg['selections'] = selections
            with accesses() as paths:
                new, files = P.build_materials(cfg, self.root / 'new', connection_snapshot={})
                upgrade, _ = U.write_upgrade(old, cfg, self.root / f'u{n}')
            self.assertUntouched(paths, self.alpha, self.beta, self.root / 'old/sources/external')
            self.assertEqual(new['preparation']['readiness'], 'READY')
            self.assertEqual(new['scope']['max_attempts'], 3)
            self.assertIn('sources/brief.md', files)
            self.assertEqual(new['source_manifest'], upgrade['source_manifest'])

    def test_P2_selected_registry_entries_only(self):
        cfg = self.config([{'key': A, 'skills': ['review']}])
        for variant in ('healthy', 'collision', 'bad_zip', 'missing'):
            if variant == 'collision':
                descriptor = self.beta / '.cursor-plugin/plugin.json'
                manifest = read_json(descriptor)
                manifest['name'] = 'alpha'
                descriptor.write_text(json.dumps(manifest))
                C.configure(self.project, 'project', 'beta', self.beta, ['base.md'])
                with self.assertRaisesRegex(ValueError, 'conflict'):
                    self.write(self.config([{'key': A}, {'key': B}]), 'collision')
            if variant == 'bad_zip':
                shutil.rmtree(self.beta)
                self.beta.write_bytes(b'invalid ZIP')
            if variant == 'missing':
                self.beta.unlink()
            with accesses() as paths:
                result = self.write(cfg, variant)
            self.assertTrue(any(p.startswith(str(self.alpha) + '/') for p in paths))
            self.assertUntouched(paths, self.beta)
            self.assertEqual(result['preparation']['readiness'], 'READY')
        broken = self.write(self.config([{'key': B}]), 'broken')
        self.assertEqual(broken['preparation']['readiness'], 'INCOMPLETE')

    def test_P3_wrong_snapshot_is_discarded(self):
        wrong = C.load_connections(self.instance, self.project, [A + ':spare'])
        cfg = self.config([{'key': A, 'skills': ['review']}])
        cold, cold_files = P.build_materials(cfg, self.root / 'same')
        for snapshot in (wrong, {}, C.load_connections(self.instance, self.project, [A + ':spare'], keys={A})):
            with accesses() as paths:
                hot, hot_files = P.build_materials(cfg, self.root / 'same', connection_snapshot=snapshot)
            self.assertEqual((hot, hot_files), (cold, cold_files))
            self.assertUntouched(paths, self.beta)
        valid = C.load_connections(self.instance, self.project, [A + ':review'], keys={A})
        with patch.object(P._connections, 'load_connections', side_effect=AssertionError('unexpected cold load')):
            self.assertEqual(P.build_materials(cfg, self.root / 'same', connection_snapshot=valid), (cold, cold_files))
        poisoned = deepcopy(valid)
        poisoned['materials'][-1]['text'] = 'other body'
        self.assertEqual(P.build_materials(cfg, self.root / 'same', connection_snapshot=poisoned), (cold, cold_files))
        C.configure(self.instance, 'instance', 'alpha', enabled=False)
        with self.assertRaisesRegex(ValueError, 'disabled'):
            P.build_materials(cfg, self.root / 'output', connection_snapshot=wrong)

    def test_P4_same_id_changes_and_immediate_baseline(self):
        cfg = self.config([{'key': A, 'skills': ['spare']}])
        old = self.write(cfg, 'O')
        cfg['connections']['build'][0]['skills'] = ['review']
        with accesses() as paths:
            swapped, t = U.write_upgrade(old, cfg, self.root / 'S')
            self.assertEqual(t['workpack_sources'], [])
            self.assertEqual(t['source_affected_workpacks'], ['MAKE'])
            self.assertEqual(len(t['source_files']), 1)
            before, after = t['source_files'][0]['before'], t['source_files'][0]['after']
            self.assertTrue(before['path'].endswith('spare/SKILL.md'))
            self.assertTrue(after['path'].endswith('review/SKILL.md'))
            path = self.alpha / 'skills/review/SKILL.md'
            path.write_bytes(path.read_bytes() + b'Updated body\n')
            C.configure(self.instance, 'instance', 'alpha', self.alpha, ['base.md'])
            new, _ = U.write_upgrade(swapped, cfg, self.root / 'N')
            changed = read_json(self.root / 'N/transition.json')
            self.assertEqual(changed['workpack_sources'], [])
            self.assertEqual(changed['source_affected_workpacks'], ['MAKE'])
            body = next(r for r in changed['source_files'] if r['after']['path'] == after['path'])
            self.assertEqual(body['change'], 'CHANGED')
            self.assertEqual(body['before']['sha256'], after['sha256'])
            self.assertEqual(body['after']['sha256'], C.digest(path.read_bytes()))
            repeat, _ = U.write_upgrade(read_json(self.root / 'N/materials.json'), cfg, self.root / 'R')
            report = read_json(self.root / 'R/transition.json')
            for k in ('workpack_sources', 'source_affected_workpacks', 'source_files'):
                self.assertEqual(report[k], [])
            for row in new['source_manifest']:
                self.assertEqual((self.root / 'N/sources' / row['path']).read_bytes(),
                                 (self.root / 'R/sources' / row['path']).read_bytes())
            self.assertEqual(new['source_manifest'], repeat['source_manifest'])
        self.assertUntouched(paths, self.beta)

        # A newly bound source may share a key with an inaccessible old root.
        previous = self.write(self.legacy(), 'previous')
        relocated = self.root / 'alpha-new'
        shutil.copytree(self.alpha, relocated)
        C.configure(self.instance, 'instance', 'alpha', relocated, ['base.md'])
        cfg = self.config([{'key': A, 'skills': ['review']}], [{'key': B, 'mode': 'CATALOG_ONLY'}])
        with accesses() as paths:
            U.write_upgrade(previous, cfg, self.root / 'relocated')
        self.assertUntouched(paths, self.alpha, self.beta, self.root / 'previous/sources/external')

    def test_P5_invalid_selection_before_io(self):
        for update in ({'selection_version': 2}, {'selection_version': True}, {'build': None}, {'target': {}},
                       {'native': [{'key': B}]}, {'feature_selections': [{'key': B}]}, {'skills': [B + ':reference']},
                       {'build': [{'key': 'instance.missing'}]}, {'build': [{'key': A, 'skills': ['missing']}]},
                       {'target': [{'key': A, 'mode': 'typo'}]}):
            cfg = self.config()
            cfg['connections'].update(update)
            with accesses() as paths, self.assertRaises(ValueError):
                self.write(cfg, 'invalid')
            self.assertUntouched(paths, self.alpha, self.beta)
        for field in ('build', 'target', 'selection_version'):
            cfg = self.config()
            del cfg['connections'][field]
            with self.assertRaises(ValueError):
                self.write(cfg, 'missing')

    @contextmanager
    def inner_checks(self, fail_at=None):
        original_module = D.module
        observed = []
        def load_module(name):
            module = original_module(name)
            if name == 'stack_handoff':
                check = module._consume._prepare.check_selection
                def inner(materials):
                    guide = self.builtin / 'guide.md'
                    original = guide.read_bytes()
                    self.assertNotIn(A, json.dumps(materials))
                    observed.append([r['name'] for r in materials['preparation']['selections']])
                    try:
                        if fail_at == len(observed):
                            guide.write_bytes(b'Changed at this phase only.')
                        return check(materials)
                    finally:
                        if fail_at == len(observed):
                            guide.write_bytes(original)
                module._consume._prepare.check_selection = inner
            return module
        with patch.object(D, 'module', load_module):
            yield observed

    def test_D1_build_only_outer_and_inner(self):
        for i, target in enumerate(([], [{'key': B, 'mode': 'METHODS', 'skills': ['reference']}])):
            cfg = self.config([{'key': A, 'skills': ['review']}], target)
            cfg['selections'] = [self.local]
            name = f'd1{i}'
            self.write(cfg, name)
            self.assertIn(b'alpha-review-BODY', (self.root / name / 'sources/external/instance.alpha/materials/skills/review/SKILL.md').read_bytes())
            with accesses() as paths, self.inner_checks() as checks:
                d = D.prepare_delivery(read_json(self.root / name / 'materials.json'), self.root / ('out' + name))
            self.assertUntouched(paths, self.alpha, self.root / name / 'sources/external/instance.alpha')
            self.assertEqual(checks, [['local'], ['local']])
            self.assertEqual([r['key'] for r in d['external']], [r['key'] for r in target])
            self.assertFalse((self.root / ('out' + name) / 'external' / A).exists())

    def test_D2_catalog_only_is_passive(self):
        m = self.write(self.config(target=[{'key': A, 'mode': 'CATALOG_ONLY', 'skills': ['review']}]), 'm')
        d = D.prepare_delivery(m, self.root / 'pub')
        entry = d['external'][0]
        self.assertEqual(set(entry['material_files']), {'LICENSE'})
        self.assertEqual([s['name'] for s in entry['catalog']['skills']], ['review'])
        self.assertNotIn('path', entry['catalog']['skills'][0])
        self.assertFalse(any(b'alpha-review-BODY' in p.read_bytes() for p in (self.root / 'pub').rglob('*') if p.is_file()))

    def test_D3_directory_and_zip_closures(self):
        for i, src in enumerate((self.alpha, self.root / 'alpha.zip')):
            if i:
                with ZipFile(src, 'w') as archive:
                    for p in self.alpha.rglob('*'):
                        if p.is_file():
                            archive.write(p, 'package/' + p.relative_to(self.alpha).as_posix())
                C.configure(self.instance, 'instance', 'alpha', src, ['base.md'])
            m = self.write(self.config(target=[{'key': A, 'mode': 'METHODS', 'skills': ['review'], 'files': ['base.md']}]), f'm{i}')
            output = self.root / f'pub{i}'
            d = D.prepare_delivery(m, output)
            row = d['external'][0]
            expected = {'skills/review/SKILL.md', 'base.md', 'LICENSE'}
            self.assertEqual(set(row['material_files']), expected)
            self.assertEqual({p.relative_to(output / row['root']).as_posix() for p in (output / row['root']).rglob('*') if p.is_file()}, expected)
            with self.assertRaisesRegex(ValueError, 'catalog-only'):
                D.bind_delivery(output, A, {}, project_root=self.project)

    def test_D4_explicit_all_and_target_subset(self):
        for i, mode in enumerate(('METHODS', 'ALL')):
            conf = self.config([{'key': A, 'skills': ['review', 'spare']}], [{'key': A, 'mode': mode, 'skills': ['review']}])
            row = D.prepare_delivery(self.write(conf, f'm{i}'), self.root / f'd{i}')['external'][0]
            self.assertEqual('skills/spare/SKILL.md' in row['material_files'], mode == 'ALL')
            self.assertIn('skills/review/SKILL.md', row['material_files'])

        # Drive the existing feature-mapped native path with its own target
        # operation list. No sibling runtime or Skill may appear in the package.
        from tests.test_capability_feature_delivery import ExternalSubsetTests
        fx = ExternalSubsetTests()
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        fx.feature_setup()
        conf = fx.config['connections']
        native = {**conf['native'][0], 'operations': ['sum']}
        feature = {**conf['feature_selections'][0], 'mapping_sha256': C.digest(fx.map_path.read_bytes())}
        conf.update(selection_version=1, build=[{'key': 'instance.demo'}],
                    target=[{'key': 'instance.demo', 'mode': 'NATIVE', 'native': native, 'feature_selection': feature}])
        selected = P.write_materials(fx.config, fx.root / 'scoped')
        row = D.prepare_delivery(selected, fx.output)['external'][0]
        self.assertEqual(row['operations'], ['sum'])
        self.assertFalse((fx.output / row['root'] / 'skills/spare').exists())
        self.assertEqual(fx.bind()['operations'], ['sum'])
        with patch.object(P._connections, 'load_connections', wraps=P._connections.load_connections) as calls:
            hot, _ = P.build_materials(fx.config, fx.root / 'hot', connection_snapshot={'diagnostics': ['foreign']})
            self.assertEqual([call.kwargs['keys'] for call in calls.call_args_list], [{'instance.demo'}] * 2)
            self.assertEqual(hot['preparation']['external_connections'], selected['preparation']['external_connections'])
        # The feature selection can also belong exclusively to the target.
        conf.update(build=[], native=[], feature_selections=[])
        with accesses() as paths:
            target_only = P.write_materials(fx.config, fx.root / 'target-only')
        self.assertUntouched(paths, fx.source, fx.map_path, fx.adapter)
        self.assertEqual(D.prepare_delivery(target_only, fx.root / 'target-native')['external'][0]['operations'], ['sum'])

    def test_D5_each_inner_check_rejects_transient_drift(self):
        cfg = self.config([{'key': A, 'skills': ['review']}])
        cfg['selections'] = [self.local]
        m = self.write(cfg, 'm')
        for stage in (1, 2):
            output = self.root / f'out{stage}'
            with accesses() as paths, self.inner_checks(stage) as observed, self.assertRaisesRegex(ValueError, 'changed'):
                D.prepare_delivery(m, output)
            self.assertUntouched(paths, self.alpha, self.root / 'm/sources/external')
            self.assertEqual(observed, [['local']] * stage)
            for name in ('builtin/delivery.json', 'delivery.json'):
                self.assertFalse((output / name).exists())

        config = self.config(target=[{'key': B, 'mode': 'METHODS', 'skills': ['reference'], 'files': ['base.md']}])
        target = self.write(config, 'target')
        (self.beta / 'base.md').unlink()
        with self.assertRaisesRegex(ValueError, 'project.beta'):
            D.prepare_delivery(target, self.root / 'missing-ref')
        self.assertFalse((self.root / 'missing-ref/delivery.json').exists())

    def test_L1_legacy_repeat_and_fragment(self):
        cfg = self.legacy()
        m = self.write(cfg, 'one')
        cfg.update(base_materials=m, source_root=str(self.root / 'one/sources'))
        self.assertEqual(self.write(cfg, 'two')['source_manifest'], m['source_manifest'])
        cfg['connections']['skills'] = [A + ':spare', B + ':reference']
        more = self.write(cfg, 'three')
        self.assertEqual({r['path'] for r in more['source_manifest']} - {r['path'] for r in m['source_manifest']},
                         {f'external/{k}/materials/skills/{s}/SKILL.md' for k,s in ((A,'spare'),(B,'reference'))})
        del m['request']
        with self.assertRaisesRegex(ValueError, 'existing request'):
            self.write(cfg, 'fragment')

        from tests.test_capability_feature_delivery import ExternalSubsetTests
        fx = ExternalSubsetTests()
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        fx.feature_setup()
        C.configure(fx.instance, 'instance', 'other', self.beta)
        conn = fx.config['connections']
        conn['skills'] = ['instance.demo:spare', 'instance.other:reference']
        mapped, files = P.build_materials(fx.config, fx.root / 'mapped')
        def bodies(files):
            return {name for name in files if '/materials/skills/' in name and name.endswith('/SKILL.md')}
        def expected(skill):
            return {'sources/external/instance.demo/materials/skills/' + skill + '/SKILL.md',
                    'sources/external/instance.other/materials/skills/reference/SKILL.md'}
        self.assertEqual(bodies(files), expected('sum'))
        self.assertEqual(mapped['native_bindings']['instance.demo']['operations'], ['sum'])
        del conn['feature_selections']
        restored, files = P.build_materials(fx.config, fx.root / 'unmapped')
        self.assertEqual(bodies(files), expected('spare'))
        self.assertEqual(set(restored['native_bindings']['instance.demo']['operations']), {'sum', 'spare'})
        ids = {r['source_id'] for r in restored['source_manifest'] if 'sources/' + r['path'] in expected('spare')}
        self.assertEqual(len(ids), 2)
        self.assertTrue(ids <= {r['id'] for r in restored['request']['plan']['workpacks'][0]['inputs']})
        self.assertTrue(all(name in files for name in ('sources/external/instance.demo/_connection/catalog.json',
                                                      'sources/external/instance.other/_connection/catalog.json')))

    def test_L2_legacy_delivery_keeps_bodies_and_checks(self):
        m = self.write(self.legacy(), 'm')
        self.assertIn('skills/review/SKILL.md', D.prepare_delivery(m, self.root / 'd')['external'][0]['material_files'])
        (self.beta / 'base.md').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            load('stack_handoff').public_delivery(m, self.root / 'bad')

    def test_L3_legacy_drift_and_scoped_deselection(self):
        third = self.package('extra')
        legacy_registry = (self.instance / C.REGISTRY).read_bytes()
        C.configure(self.instance, 'instance', 'extra', third, on_demand=True)
        with accesses() as paths:
            visible = C.load_connections(self.instance, self.project)
        self.assertUntouched(paths, third, self.instance / C.ON_DEMAND_REGISTRY)
        self.assertEqual({r['key'] for r in visible['connections']}, {A, B})
        self.assertEqual((self.instance / C.REGISTRY).read_bytes(), legacy_registry)
        only = self.write(self.config([{'key': 'instance.extra', 'skills': ['review']}]), 'opt-in')
        self.assertEqual([r['key'] for r in only['preparation']['external_connections']], ['instance.extra'])
        C.configure(self.instance, 'instance', 'extra', enabled=False, on_demand=True)
        self.assertEqual(P.check_selection(only)['status'], 'MATCH')
        with self.assertRaisesRegex(ValueError, 'disabled'):
            self.write(self.config([{'key': 'instance.extra'}]), 'disabled-new')
        with self.assertRaisesRegex(ValueError, 'legacy project base'):
            P.build_materials({**self.legacy(), 'base_materials': only}, self.root / 'leak')
        old = self.write(self.legacy(), 'old')
        self.assertEqual(U.build_upgrade(old, self.legacy(), self.root / 'healthy')[2]['previous_selection_check']['status'], 'MATCH')
        (self.beta / 'base.md').write_text('Changed after capture')
        self.assertEqual(U.build_upgrade(old, self.legacy(), self.root / 'stale')[2]['previous_selection_check']['status'], 'CHANGED')
        with accesses() as paths:
            new, report = U.write_upgrade(old, self.config(), self.root / 'next')
            self.assertEqual(report['previous_selection_check']['status'], 'PARTIALLY_CHECKED')
            self.assertEqual({r['key'] for r in report['previous_selection_check']['external_not_rechecked']}, {A, B})
            with self.assertRaisesRegex(ValueError, 'consumer'):
                D.prepare_delivery(new, self.root / 'wrong-consumer', consumer_protocol=0)
            mixed = self.config()
            mixed.update(base_materials=old, source_root=str(self.root / 'old/sources'))
            with self.assertRaisesRegex(ValueError, 'project base'):
                U.write_upgrade(old, mixed, self.root / 'mixed')
        self.assertUntouched(paths, self.beta, self.alpha, self.root / 'old/sources/external')
