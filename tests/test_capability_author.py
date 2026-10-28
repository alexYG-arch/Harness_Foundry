"""E5 engineering samples, not model or production-service acceptance."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'examples/capability-adapters'
spec = importlib.util.spec_from_file_location('tested_author', BASE / 'author.py')
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
from harness_foundry_factory.process_observation import CommandObservation


class ExternalAuthorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='外接 author '); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve(); self.source = self.root / 'original'; self.source.mkdir()
        self.output = self.root / 'candidate'; self.host = self.root / 'host'; self.host.mkdir()
        self.project = self.root / 'project'; self.project.mkdir()
        (self.source / 'lib').mkdir()
        (self.source / 'lib/cli.py').write_text('from decimal import Decimal\nimport json,sys\ntry:\n print(json.dumps({"sum":str(sum(map(Decimal,sys.argv[1:]), Decimal(0)))}))\nexcept Exception:\n print("invalid",file=sys.stderr);sys.exit(2)\n')
        (self.source / 'guide.md').write_text('Original decimal CLI. Arguments are decimal numbers. No network.')
        self.document = {'package': {'id': 'pocketcalc', 'release': '3', 'license': 'MIT'},
                         'entry': 'lib/cli.py', 'lifecycle': {'refresh': 'manual upstream selection'},
                         'side_effects': {'cache': 'unknown'}, 'auth': {'method': 'provider-owned'}}
        (self.source / 'toolbox.json').write_text(json.dumps(self.document))
        self.request = {'descriptor': 'toolbox.json', 'format': 'json', 'adapter_version': '1',
            'runtime_files': ['lib/*', 'guide.md'], 'materials': ['guide.md'],
            'mapping': {'provider': {'$pointer': '/package/id'}, 'version': {'$pointer': '/package/release'},
                'license': {'$pointer': '/package/license'}, 'operations': {
                    'sum': {'argv': ['tool:python', 'package:lib/cli.py'], 'tools': ['python'],
                            'effects': [], 'requirements': ['decimal arguments']}}}}

    def state(self, root):
        return {p.relative_to(root).as_posix(): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
                for p in root.rglob('*') if p.is_file()}

    def convert(self): return A.write_candidate(self.request, self.source, self.output)

    def binding(self, operations=None, tools=None):
        A.C.configure(self.host, 'instance', 'pocket', self.output / 'package')
        connection = A.C.load_connections(self.host)['connections'][0]
        config = {'root': str(self.output / 'package'), 'adapter_path': str(self.output / 'adapter.json'),
                  'environment_bindings': tools or {'python': {'path': sys.executable}}}
        if operations: config['operations'] = operations
        return A.N.bind_native(connection, config, project_root=self.project)

    def test_conversion_deterministic_preserves_original_and_unknown_fields(self):
        old = self.state(self.source)
        with patch('subprocess.Popen', side_effect=AssertionError('no dispatch')):
            first = self.convert(); saved = self.state(self.output); second = self.convert()
        self.assertFalse(first['reused']); self.assertTrue(second['reused'])
        self.assertEqual(saved, self.state(self.output)); self.assertEqual(old, self.state(self.source))
        report = json.loads((self.output / 'mapping-report.json').read_text())
        self.assertEqual(report['original_document'], self.document)
        self.assertIn('/side_effects/cache', {r['pointer'] for r in report['unmapped']})
        self.assertIn('/auth/method', {r['pointer'] for r in report['unmapped']})
        self.assertFalse(report['acceptance_granted']); self.assertFalse(report['budget_modified'])
        self.assertNotIn('side_effects', (self.output / 'package/capability.json').read_text())

    def test_second_provider_actual_native_cli_and_recovery(self):
        self.convert(); binding = self.binding()
        call = A.N.prepare_call(binding, 'sum', ['0.10', '2.30', '-0.40'], cwd=self.project)
        obs = CommandObservation(self.root / 'observation', 'E5-CLI-1', 'LOCAL'); self.addCleanup(obs.close)
        A.N.attach_call(obs, call)
        run = subprocess.run(call['argv'], cwd=call['cwd'], text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0); self.assertEqual(json.loads(run.stdout), {'sum': '2.00'})
        result = {'exit_code': run.returncode, 'stdout': run.stdout, 'stderr': run.stderr, 'status': 'COMPLETED'}
        obs.finished(result)
        (self.output / 'package/upstream/lib/cli.py').unlink()
        with patch('subprocess.Popen', side_effect=AssertionError('read only')):
            first = A.N.recover_call(obs.root, 'E5-CLI-1', 'LOCAL')
            second = A.N.recover_call(obs.root, 'E5-CLI-1', 'LOCAL')
        self.assertEqual(first, second); self.assertEqual(first['result'], result)
        self.assertFalse(first['replay_allowed'])

    def test_module_layout_wrong_input_and_equivalent_numbers(self):
        self.convert(); binding = self.binding()
        for args, expected in [(['1e1', '-2.5'], '7.5'), ([], '0')]:
            call = A.N.prepare_call(binding, 'sum', args, cwd=self.project)
            run = subprocess.run(call['argv'], text=True, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0); self.assertEqual(json.loads(run.stdout), {'sum': expected})
        call = A.N.prepare_call(binding, 'sum', ['bad'], cwd=self.project)
        run = subprocess.run(call['argv'], text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 2); self.assertEqual(run.stderr.strip(), 'invalid')

    def test_toml_pointer_and_raw_version_binding(self):
        self.request.update(descriptor='toolbox.toml', format='toml')
        (self.source / 'toolbox.toml').write_text('[package]\nid="pocketcalc"\nrelease="3"\nlicense="MIT"\n[extra]\nupdate="not mapped"\n')
        self.convert(); report = json.loads((self.output / 'mapping-report.json').read_text())
        self.assertIn('/extra/update', [r['pointer'] for r in report['unmapped']])
        old = self.state(self.output)
        (self.source / 'toolbox.toml').write_text('[package]\nid="pocketcalc"\nrelease="4"\nlicense="MIT"\n')
        with self.assertRaisesRegex(ValueError, 'existing candidate'): self.convert()
        self.assertEqual(old, self.state(self.output))
        self.output = self.root / 'v4'; self.convert()
        self.assertEqual(json.loads((self.output / 'package/capability.json').read_text())['version'], '4')

    def test_yaml_and_readme_remain_explicit_candidate_not_guessed(self):
        for index, text in enumerate(('name: pocket\nrefresh: !!python/object:unknown\n', '# CLI\nRun a selected tool; update rules unknown.\n')):
            self.request.update(descriptor='notes.txt', format='text')
            (self.source / 'notes.txt').write_text(text)
            self.request['mapping'].update(provider='pocketcalc', version='3', license='UNKNOWN')
            self.output = self.root / ('text-' + str(index)); self.convert()
            report = json.loads((self.output / 'mapping-report.json').read_text())
            self.assertEqual(report['original_document'], {'text': text})
            self.assertEqual(report['unmapped'], [{'pointer': '/text', 'value': text}])
            self.assertEqual(report['status'], 'CANDIDATE')

    def test_unknown_operation_does_not_hide_usable_operation(self):
        self.request['mapping']['operations']['upload'] = {'argv': ['tool:unknown'], 'effects': ['remote write']}
        self.convert(); report = json.loads((self.output / 'mapping-report.json').read_text())
        self.assertEqual(report['available_operations'], ['sum'])
        self.assertEqual(report['unresolved_operations'][0]['operation'], 'upload')
        self.assertIn('remote write', report['unresolved_operations'][0]['declared']['effects'])
        self.assertEqual(self.binding()['operations'], ['sum'])

    def test_no_operations_is_material_only_not_invented_command(self):
        self.request['mapping'].pop('operations'); self.convert()
        A.C.configure(self.host, 'instance', 'pocket', self.output / 'package')
        self.assertEqual(A.C.load_connections(self.host)['status'], 'READY')
        self.assertEqual(json.loads((self.output / 'adapter.json').read_text())['operations'], {})

    def test_missing_identity_or_pointer_does_not_write(self):
        for value in ({'$pointer': '/absent'}, None):
            self.request['mapping']['provider'] = value
            with self.assertRaises((ValueError, KeyError)): self.convert()
            self.assertFalse(self.output.exists())

    def test_duplicate_json_and_unsupported_format_are_not_guessed(self):
        (self.source / 'toolbox.json').write_text('{"package":{},"package":{}}')
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.convert()
        self.request['format'] = 'yaml'
        with self.assertRaisesRegex(ValueError, 'select json'): self.convert()

    def test_missing_selected_file_does_not_use_development_copy(self):
        self.request['runtime_files'].append('missing-tool')
        with self.assertRaisesRegex(ValueError, 'no files'): self.convert()
        self.assertFalse(self.output.exists())

    def test_modes_and_contained_file_link_preserved(self):
        source = self.source / 'lib/cli.py'; source.chmod(0o751)
        (self.source / 'lib/alias.py').symlink_to('cli.py')
        self.convert()
        path = self.output / 'package/upstream/lib/alias.py'
        self.assertTrue(path.is_symlink()); self.assertEqual(os.readlink(path), 'cli.py')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o751)
        self.assertTrue(self.convert()['reused'])

    def test_missing_link_target_and_escape_are_explicit(self):
        (self.source / 'lib/alias.py').symlink_to('cli.py')
        self.request['runtime_files'] = ['lib/alias.py', 'guide.md']
        with self.assertRaisesRegex(ValueError, 'link target'): self.convert()
        (self.source / 'lib/alias.py').unlink(); (self.root / 'outside').write_text('outside')
        (self.source / 'lib/alias.py').symlink_to(self.root / 'outside')
        with self.assertRaisesRegex(ValueError, 'inside'): self.convert()

    def test_multihop_link_missing_intermediate_rejected_before_write(self):
        (self.source / 'lib/middle.py').symlink_to('cli.py')
        (self.source / 'lib/alias.py').symlink_to('middle.py')
        self.request['runtime_files'] = ['lib/alias.py', 'lib/cli.py', 'guide.md']
        with self.assertRaisesRegex(ValueError, 'link target'):
            self.convert()
        self.assertFalse(self.output.exists())

    def test_complete_multihop_and_parent_relative_links_remain_callable(self):
        (self.source / 'lib/middle.py').symlink_to('./cli.py')
        (self.source / 'bin').mkdir()
        (self.source / 'bin/alias.py').symlink_to('../lib/middle.py')
        self.request['runtime_files'].append('bin/*')
        self.request['mapping']['operations']['sum']['argv'][1] = 'package:bin/alias.py'
        self.convert()
        alias = self.output / 'package/upstream/bin/alias.py'
        self.assertEqual(os.readlink(alias), '../lib/middle.py')
        self.assertEqual(os.readlink(alias.parent.parent / 'lib/middle.py'), './cli.py')
        self.assertEqual(alias.read_bytes(), (self.source / 'lib/cli.py').read_bytes())
        call = A.N.prepare_call(self.binding(), 'sum', ['0.1', '0.2'], cwd=self.project)
        run = subprocess.run(call['argv'], capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), {'sum': '0.3'})
        self.assertTrue(self.convert()['reused'])

    def test_link_traversal_preserves_needed_directories_without_copying_contents(self):
        (self.source / 'lib/spare/inner').mkdir(parents=True)
        (self.source / 'lib/spare/private.txt').write_text('not selected')
        alias = self.source / 'lib/alias.py'
        self.request['mapping']['operations']['sum']['argv'][1] = 'package:lib/alias.py'
        for ordinal, target in enumerate(('spare/../cli.py', './spare/inner/../../cli.py')):
            with self.subTest(target=target):
                if alias.is_symlink(): alias.unlink()
                alias.symlink_to(target)
                self.output = self.root / ('layout-' + str(ordinal))
                self.convert(); copied = self.output / 'package/upstream/lib/alias.py'
                self.assertEqual(os.readlink(copied), target)
                self.assertTrue((copied.parent / 'spare').is_dir())
                self.assertFalse((copied.parent / 'spare/private.txt').exists())
                self.assertEqual(copied.read_bytes(), (self.source / 'lib/cli.py').read_bytes())
                call = A.N.prepare_call(self.binding(), 'sum', ['0.1', '0.2'], cwd=self.project)
                run = subprocess.run(call['argv'], capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(json.loads(run.stdout), {'sum': '0.3'})
                self.assertTrue(self.convert()['reused'])

    def test_reuse_rejects_missing_traversal_directory_without_repair_or_dispatch(self):
        (self.source / 'lib/spare').mkdir()
        (self.source / 'lib/alias.py').symlink_to('spare/../cli.py')
        self.convert()
        spare = self.output / 'package/upstream/lib/spare'
        # On the old implementation this directory is missing from the outset.
        if spare.is_dir(): spare.rmdir()
        copied = self.output / 'package/upstream/lib/alias.py'
        self.assertTrue(copied.is_symlink()); self.assertFalse(copied.exists())
        before = self.state(self.output)
        with patch('subprocess.Popen', side_effect=AssertionError('no dispatch')):
            with self.assertRaisesRegex(ValueError, 'existing candidate'):
                self.convert()
        self.assertEqual(before, self.state(self.output))
        self.assertFalse(spare.exists()); self.assertEqual(os.readlink(copied), 'spare/../cli.py')

    def test_link_traversal_directory_alias_requires_explicit_layout(self):
        (self.source / 'lib/sub/deep').mkdir(parents=True)
        (self.source / 'lib/sub/cli.py').write_text('different original target')
        (self.source / 'lib/jump').symlink_to('sub/deep', target_is_directory=True)
        (self.source / 'lib/alias.py').symlink_to('jump/../cli.py')
        self.request['runtime_files'].append('lib/sub/cli.py')
        self.assertEqual((self.source / 'lib/alias.py').read_text(), 'different original target')
        with self.assertRaisesRegex(ValueError, 'directory link.*explicit'):
            self.convert()
        self.assertFalse(self.output.exists())

    def test_array_pointer_rejects_python_index_aliases_before_write(self):
        self.document['ids'] = ['first', 'last']
        (self.source / 'toolbox.json').write_text(json.dumps(self.document))
        for ordinal, index in enumerate(('-1', '01', '+1', ' 1', '١')):
            self.output = self.root / ('bad-index-' + str(ordinal))
            with self.subTest(index=index):
                self.request['mapping']['provider'] = {'$pointer': '/ids/' + index}
                with self.assertRaisesRegex(ValueError, 'array index'):
                    self.convert()
                self.assertFalse(self.output.exists())

    def test_array_pointer_valid_indices_and_object_keys_preserved(self):
        document = {'ids': ['first', 'last'], '-1': 'object key', 'a/b': {'~value': 'escaped'}}
        self.assertEqual(A.pointer(document, '/ids/0'), 'first')
        self.assertEqual(A.pointer(document, '/ids/1'), 'last')
        self.assertEqual(A.pointer(document, '/-1'), 'object key')
        self.assertEqual(A.pointer(document, '/a~1b/~0value'), 'escaped')
        with self.assertRaises(IndexError): A.pointer(document, '/ids/2')

    def test_toml_non_json_scalars_keep_raw_types_and_candidate_reuse(self):
        self.request.update(descriptor='toolbox.toml', format='toml')
        raw = b'[package]\nid="pocketcalc"\nrelease="3"\nlicense="MIT"\n[extra]\nday=2026-10-26\nclock=10:20:30.125\nat=2026-10-26T10:20:30+08:00\nlocal=2026-10-26T10:20:30\nvalues=[inf,-inf,nan]\n'
        (self.source / 'toolbox.toml').write_bytes(raw)
        self.convert()
        def reject_constant(value): raise AssertionError('non-JSON constant ' + value)
        report = json.loads((self.output / 'mapping-report.json').read_text(), parse_constant=reject_constant)
        self.assertEqual((self.output / 'source-descriptor.bin').read_bytes(), raw)
        self.assertEqual(report['original_document']['extra'], {
            'day': '2026-10-26', 'clock': '10:20:30.125000', 'at': '2026-10-26T10:20:30+08:00',
            'local': '2026-10-26T10:20:30', 'values': ['inf', '-inf', 'nan']})
        types = {r['pointer']: r['type'] for r in report['report_scalar_types']}
        self.assertEqual(types['/original_document/extra/day'], 'date')
        self.assertEqual(types['/original_document/extra/clock'], 'time')
        self.assertEqual(types['/original_document/extra/at'], 'datetime')
        self.assertEqual(types['/original_document/extra/local'], 'datetime')
        self.assertEqual(types['/original_document/extra/values/2'], 'float')
        unknown = {r['pointer']: r['value'] for r in report['unmapped']}
        self.assertEqual(unknown['/extra/day'], '2026-10-26')
        self.assertEqual(unknown['/extra/values/2'], 'nan')
        saved = self.state(self.output)
        self.assertTrue(self.convert()['reused']); self.assertEqual(saved, self.state(self.output))
        self.assertEqual(self.binding()['operations'], ['sum'])

    def test_original_output_overlap_and_partial_output_preserve_bytes(self):
        self.output = self.source / 'generated'
        with self.assertRaisesRegex(ValueError, 'separate'): self.convert()
        self.output = self.root / 'partial'; self.output.mkdir(); (self.output / 'old.txt').write_text('old')
        before = self.state(self.output)
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.convert()
        self.assertEqual(before, self.state(self.output))

    def test_changed_runtime_requires_new_native_binding(self):
        self.convert(); binding = self.binding()
        (self.output / 'package/upstream/lib/cli.py').write_text('different')
        with self.assertRaisesRegex(ValueError, 'changed'): A.N.prepare_call(binding, 'sum', cwd=self.project)

    def exercise_actual_compile_and_declared_derived_wrapper(self):
        compiler = shutil.which('cc')
        self.assertIsNotNone(compiler, 'E5 engineering compile sample requires a declared C compiler')
        (self.source / 'lib/count.c').write_text('#include <stdio.h>\n#include <string.h>\nint main(int argc,char **argv){if(argc!=2)return 2;printf("%zu\\n",strlen(argv[1]));return 0;}\n')
        # Authored wrapper changes the output protocol only. Original C stays intact.
        (self.source / 'lib/wrap.py').write_text('import json,subprocess,sys\nr=subprocess.run(sys.argv[1:],capture_output=True,text=True)\nif r.returncode:sys.exit(r.returncode)\nprint(json.dumps({"bytes":int(r.stdout)}))\n')
        self.request['mapping']['operations'].update({
            'compile': {'argv': ['tool:cc', 'package:lib/count.c'], 'tools': ['cc'], 'effects': ['declared binary output'], 'requirements': ['declared toolchain and output']},
            'json-count': {'argv': ['tool:python', 'package:lib/wrap.py', 'tool:counter'], 'tools': ['python', 'counter'], 'effects': [], 'requirements': ['compiled counter']}})
        self.request['build'] = {'operation': 'compile', 'toolchain': 'selected cc', 'dependencies': 'C standard library', 'reproducibility': 'same host only'}
        self.request['changes'] = [{'file': 'lib/wrap.py', 'kind': 'DERIVED_WRAPPER', 'difference': 'decimal stdout converted to JSON; original exit preserved'}]
        original = self.state(self.source); self.convert()
        b = self.binding(['compile'], {'cc': {'path': compiler}})
        binary = self.project / 'counter'
        call = A.N.prepare_call(b, 'compile', ['-o', str(binary)], cwd=self.project)
        compiled = subprocess.run(call['argv'], text=True, capture_output=True, timeout=60)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        b = self.binding(['json-count'], {'python': {'path': sys.executable}, 'counter': {'path': str(binary)}})
        for args, expected in [(['A b'], 3), ([''], 0), (['汉'], 3)]:
            call = A.N.prepare_call(b, 'json-count', args, cwd=self.project)
            run = subprocess.run(call['argv'], text=True, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr); self.assertEqual(json.loads(run.stdout), {'bytes': expected})
        call = A.N.prepare_call(b, 'json-count', [], cwd=self.project)
        self.assertEqual(subprocess.run(call['argv'], capture_output=True, timeout=20).returncode, 2)
        self.assertEqual(original, self.state(self.source))

    def test_generic_cli_prepares_no_process_and_preserves_failure_details_locally(self):
        path = self.root / 'request.json'; path.write_text(json.dumps(self.request))
        run = subprocess.run([sys.executable, '-I', '-B', str(BASE / 'author.py'), '--request', str(path),
                              '--source-root', str(self.source), '--output', str(self.output)], text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr); self.assertFalse(json.loads(run.stdout)['commands_executed'])

    def test_packaging_includes_author_and_guide(self):
        from devtools.package_generic_release import collect_files
        files = collect_files(ROOT)
        for name in ('author.py', 'AUTHORING.md'):
            self.assertEqual(files['examples/capability-adapters/' + name], (BASE / name).read_bytes())


if __name__ == '__main__': unittest.main()
