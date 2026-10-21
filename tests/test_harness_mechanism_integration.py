"""S3 material/report integration only; no Build store, model or S4 dispatch."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_runtime import _validate_scope
from harness_foundry_factory.verification_resources import (
    allocate_resources, collect_resource_reports, validate_resources, validate_structured_result,
)
from harness_foundry_factory.verification_snapshot import snapshot_verifier


EXAMPLE = Path(__file__).resolve().parents[1]/'examples/harness-composition-upgrade'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATERIALS = load(EXAMPLE/'integration/mechanism_requests.py', 'mechanism_materials')


class MechanismIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='r3-mechanism-s3-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.verifier = self.root/'verifier-source'
        shutil.copytree(EXAMPLE/'verifier', self.verifier)
        self.source = self.root/'source'
        self.source.mkdir()
        self.document = self.source/'BUILD.md'
        self.document.write_text('# Isolated mechanism build\nPreserve the configured user content and verify actual behavior.\n')
        self.control = self.root/'control'/'never-created.sqlite3'
        self.control.parent.mkdir()
        self.sequence = 0

    def bindings(self, kind, stage='v2'):
        self.sequence += 1
        suffix = stage + '-' + str(self.sequence)
        current = self.root/(kind + '-current-' + suffix)
        fixture = EXAMPLE/'mechanisms'/kind
        previous = 'custom/current' if stage in ('v1', 'v2') else 'expected/after-v2' if stage == 'v3' else 'expected/after-v3'
        shutil.copytree(fixture/previous, current)
        old = None if stage in ('v1', 'incremental') else self.root/(kind + '-old-' + suffix)
        new = None if stage == 'incremental' else self.root/(kind + '-new-' + suffix)
        if old:
            shutil.copytree(fixture/'versions'/('v1' if stage == 'v2' else 'v2'), old)
        if new:
            shutil.copytree(fixture/'versions'/stage, new)
        return {'program_id': 'UNIT-' + kind.upper() + '-' + stage.upper(),
            'requirement_path': str(self.document), 'workspace_root': str(self.root/(kind + '-target-' + suffix)),
            'current_root': str(current), 'component_old_root': str(old) if old else None,
            'component_new_root': str(new) if new else None, 'verification_root': str(self.verifier),
            'resource_root': str(self.root/(kind + '-resources-' + suffix)),
            'python_executable': sys.executable, 'python_read_roots': list(dict.fromkeys([sys.prefix, sys.base_prefix])),
            'codex_executable': '/usr/bin/true', 'model': 'unit-test-model-not-invoked',
            'max_attempts': 2, 'max_task_attempts': 2, 'command_timeout_seconds': 30,
            'expires_at': '2099-01-01T00:00:00Z'}

    def material(self, kind, stage='v2', phase='candidate'):
        bindings = self.bindings(kind, stage)
        if phase == 'apply':
            fixed = self.root/(kind + '-fixed-candidate')
            shutil.copytree(EXAMPLE/'mechanisms'/kind/'expected'/('after-' + stage), fixed)
            manifest = self.root/'fixed-apply.json'
            names = ['config.json', 'tools/render.py' if kind == 'doc' else 'tools/service.py']
            rows = [{'path': name, 'action': 'update',
                     'expected': {'file': os.path.relpath(Path(bindings['current_root'])/name, self.root), 'executable': False},
                     'desired': {'file': os.path.relpath(fixed/name, self.root), 'executable': False}} for name in names]
            manifest.write_text(json.dumps({'format_version': 1, 'files': rows}))
            helpers = self.root/'helpers'
            shutil.copytree(EXAMPLE/'helpers', helpers)
            bindings.update(candidate_root=str(fixed), apply_manifest=str(manifest), helpers_root=str(helpers))
        return MATERIALS.build_materials(kind, stage, phase, bindings), bindings

    def protected_run(self, kind, stage, *, mutation=None, environment=None):
        material, _ = self.material(kind, stage)
        scope, plan = material['scope'], material['request']['plan']
        config = validate_resources(scope['verification_resources'], plan,
            protected_paths=[scope['workspace_root'], scope['verification_root'], str(self.control), *scope['source_read_roots']])
        snapshot = snapshot_verifier(SimpleNamespace(database_path=self.control), plan, scope)
        protected = Path(snapshot['runtime_root'])
        product = Path(scope['workspace_root'])/'product'
        fixture = EXAMPLE/'mechanisms'/kind/('custom/current' if stage == 'v1' else 'expected/after-' + stage)
        shutil.copytree(fixture, product)
        if mutation:
            mutation(product, protected)
        product_before = {str(path.relative_to(product)): path.read_bytes()
                          for path in product.rglob('*') if path.is_file()}
        binding = allocate_resources(config, 'mechanism', {
            'program_id': 'UNIT-ONLY', 'prepared_event_id': 'UNIT-PREPARED', 'attempt_id': 'UNIT-ATTEMPT',
            'workpack_id': 'UNIT-WORKPACK', 'job_id': 'UNIT-JOB', 'command_id': 'UNIT-COMMAND', 'case_id': kind.upper() + '-CONTRACT'})
        env = {**os.environ, **binding['env'], 'FOUNDRY_VERIFIER_ROOT': str(protected)}
        if environment:
            env.update(environment)
        scratch = Path(binding['areas']['scratch'])
        (scratch/'unrelated.txt').write_text('retain other scratch files')
        completed = subprocess.run([sys.executable, '-I', '-B', str(protected/'check_mechanism_resource.py'),
            '--kind', kind, '--stage', stage, '--target', str(product)],
            cwd=product.parent, env=env, capture_output=True, text=True, timeout=20)
        observation = self.root/('unit-observation-' + str(self.sequence))
        observation.mkdir()
        collected = collect_resource_reports(binding, observation)
        self.assertEqual(collected['report_errors'], [], completed.stdout + completed.stderr)
        verdict = collected['verdict']
        evaluation = validate_structured_result(verdict, binding, completed.returncode)
        self.assertEqual({str(path.relative_to(product)): path.read_bytes()
                          for path in product.rglob('*') if path.is_file()}, product_before)
        self.assertEqual(list(scratch.glob('doc-export-*')), [])
        self.assertEqual((scratch/'unrelated.txt').read_text(), 'retain other scratch files')
        self.assertFalse(self.control.exists())
        return completed, verdict, evaluation, protected

    def test_all_candidate_stages_compile_without_creating_targets_or_authority(self):
        for kind, stages in (('doc', ('v1', 'v2', 'v3', 'incremental')), ('api', ('v1', 'v2', 'v3'))):
            for stage in stages:
                with self.subTest(kind=kind, stage=stage):
                    material, bindings = self.material(kind, stage)
                    request = material['request']
                    compile_build_plan(request['requirement_ir'], request['plan'])
                    validate_resources(material['scope']['verification_resources'], request['plan'])
                    _validate_scope(SimpleNamespace(database_path=self.control), request['plan'], material['scope'])
                    self.assertEqual(set(request), {'requirement_ir', 'plan'})
                    self.assertIsNone(material['preparation']['accepted_A'])
                    self.assertFalse(Path(bindings['workspace_root']).exists())
                    self.assertFalse(Path(bindings['resource_root']).exists())
                    self.assertFalse(self.control.exists())
                    self.assertNotIn(str(self.verifier), material['scope']['source_read_roots'])
                    self.assertEqual(material['scope']['executables']['python'], sys.executable)

    def test_apply_reads_fixed_inputs_and_uses_existing_local_scope(self):
        material, bindings = self.material('doc', phase='apply')
        task = material['request']['plan']['workpacks'][0]
        compile_build_plan(material['request']['requirement_ir'], material['request']['plan'])
        _validate_scope(SimpleNamespace(database_path=self.control), material['request']['plan'], material['scope'])
        self.assertEqual(task['executor'], 'LOCAL')
        self.assertIn(bindings['apply_manifest'], task['local_argv'])
        self.assertIn(bindings['candidate_root'], material['scope']['source_read_roots'])
        self.assertEqual(task['effects']['must_preserve'], ['data/notes.json', 'data/sources.json', 'USER_NOTES.md'])
        self.assertFalse(material['scope']['allow_model_service'])
        self.assertFalse(Path(bindings['workspace_root']).exists())
        bad = deepcopy(bindings)
        bad['candidate_root'] = bad['current_root']
        with self.assertRaisesRegex(ValueError, 'fixed input root'):
            MATERIALS.build_materials('doc', 'v2', 'apply', bad)

    def test_doc_protected_dependencies_ignore_later_source_edits(self):
        def mutate(product, protected):
            self.assertTrue((protected/'check_mechanisms.py').is_file())
            self.assertTrue((protected/'expectations/doc-v2.json').is_file())
            (self.verifier/'check_mechanisms.py').write_text('raise RuntimeError("unprotected checker loaded")\n')
            (self.verifier/'expectations/doc-v2.json').write_text('{}')
        completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=mutate)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(evaluated['status'], 'PASS')
        self.assertEqual(verdict['case_id'], 'DOC-CONTRACT')
        self.assertEqual(verdict['command_id'], 'UNIT-COMMAND')

    def test_apply_runs_declared_local_command_from_fixed_candidate_bytes(self):
        material, bindings = self.material('doc', phase='apply')
        scope = material['scope']
        task = material['request']['plan']['workpacks'][0]
        current, candidate = Path(bindings['current_root']), Path(bindings['candidate_root'])
        before = {str(path): path.read_bytes() for root in (current, candidate)
                  for path in root.rglob('*') if path.is_file()}
        workspace = Path(scope['workspace_root'])
        shutil.copytree(current, workspace)
        argv = task['local_argv']
        completed = subprocess.run([scope['executables'][argv[0]], *argv[1:]], cwd=workspace,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for path, content in before.items():
            self.assertEqual(Path(path).read_bytes(), content)
        for name in MATERIALS.PRODUCT_FILES['doc']:
            self.assertEqual((workspace/name).read_bytes(), (candidate/name).read_bytes())
        self.assertEqual(json.loads((workspace/'outputs/apply-result.json').read_text())['status'], 'APPLIED')
        self.assertFalse(self.control.exists())

    def test_v1_document_has_independent_locator_only_source_contract(self):
        completed, _, evaluated, _ = self.protected_run('doc', 'v1')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(evaluated['status'], 'PASS')

    def test_all_doc_versions_export_through_real_cli(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            with self.subTest(stage=stage):
                completed, verdict, evaluated, _ = self.protected_run('doc', stage)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(evaluated['status'], 'PASS')
                self.assertEqual(verdict['diagnostic']['scope'], 'offline-cli-exported-content')

    def test_doc_cli_main_failures_cannot_pass_via_correct_render_function(self):
        for replacement in ('pass', 'raise SystemExit(7)',
                            'args.output.write_text("wrong exported content", encoding="utf-8")'):
            with self.subTest(replacement=replacement):
                def mutate(product, protected):
                    path = product/'tools/render.py'
                    code = path.read_text()
                    original = 'args.output.write_text(result, encoding="utf-8")'
                    self.assertIn(original, code)
                    path.write_text(code.replace(original, replacement))
                completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=mutate)
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(verdict['failure_kind'], 'ASSERTION')
                self.assertEqual(verdict['errors'], [])
                self.assertEqual(evaluated['failure_domain'], 'BUSINESS_ASSERTION')
                self.assertTrue(evaluated['automatic_retry_allowed'])

    def test_doc_nonempty_body_mismatch_is_repairable_assertion(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            expected = json.loads((EXAMPLE/f'verifier/expectations/doc-{stage}.json').read_text())
            line = next(iter(expected['section_lines'].values()))[0]
            additions = {
                'extra_fact': '- 未经来源支持的额外事实。 [s1]',
                'duplicate_line': line,
                'wrong_reference': line.replace('[s1]', '[s2]') if '[s1]' in line else line.replace('[s2]', '[s1]'),
            }
            for mutation, extra in additions.items():
                with self.subTest(stage=stage, mutation=mutation):
                    def mutate(product, protected):
                        path = product/'tools/render.py'
                        code = path.read_text()
                        original = 'args.output.write_text(result, encoding="utf-8")'
                        self.assertIn(original, code)
                        before, after = line + '\n', line + '\n' + extra + '\n'
                        path.write_text(code.replace(original,
                            f'args.output.write_text(result.replace({before!r}, {after!r}, 1), encoding="utf-8")'))
                    completed, verdict, evaluated, _ = self.protected_run('doc', stage, mutation=mutate)
                    self.assertEqual(completed.returncode, 1)
                    self.assertEqual(verdict['failure_kind'], 'ASSERTION')
                    self.assertEqual(verdict['checks'][0]['status'], 'FAIL')
                    self.assertEqual(verdict['errors'], [])
                    self.assertEqual(evaluated['failure_domain'], 'BUSINESS_ASSERTION')
                    self.assertTrue(evaluated['automatic_retry_allowed'])

    def test_doc_preamble_content_is_repairable_assertion(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            expected = json.loads((EXAMPLE/f'verifier/expectations/doc-{stage}.json').read_text())
            line = next(iter(expected['section_lines'].values()))[0]
            additions = {
                'extra_fact': '- 未经来源支持的额外事实。 [s1]',
                'duplicate_line': line,
                'wrong_reference': line.replace('[s1]', '[s2]') if '[s1]' in line else line.replace('[s2]', '[s1]'),
            }
            for mutation, extra in additions.items():
                with self.subTest(stage=stage, mutation=mutation):
                    def mutate(product, protected):
                        path = product/'tools/render.py'
                        code = path.read_text()
                        original = 'args.output.write_text(result, encoding="utf-8")'
                        self.assertIn(original, code)
                        before = '# ' + expected['title'] + '\n'
                        after = before + extra + '\n'
                        path.write_text(code.replace(original,
                            f'args.output.write_text(result.replace({before!r}, {after!r}, 1), encoding="utf-8")'))
                    # protected_run also checks owned export cleanup, retained
                    # unrelated scratch, and unchanged product bytes.
                    completed, verdict, evaluated, _ = self.protected_run('doc', stage, mutation=mutate)
                    self.assertEqual(completed.returncode, 1)
                    self.assertEqual(verdict['failure_kind'], 'ASSERTION')
                    self.assertEqual(verdict['diagnostic'], 'unexpected content before first document section')
                    self.assertEqual(verdict['checks'], [{'id': 'document-content', 'status': 'FAIL'}])
                    self.assertEqual(verdict['errors'], [])
                    self.assertEqual(evaluated['failure_domain'], 'BUSINESS_ASSERTION')
                    self.assertTrue(evaluated['automatic_retry_allowed'])

    def test_doc_preamble_blank_variations_pass_resource_check(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            expected = json.loads((EXAMPLE/f'verifier/expectations/doc-{stage}.json').read_text())
            for name, gap in (('no_blank_line', ''), ('whitespace_lines', '\n \t\n\n')):
                with self.subTest(stage=stage, whitespace=name):
                    def mutate(product, protected):
                        path = product/'tools/render.py'
                        code = path.read_text()
                        original = 'args.output.write_text(result, encoding="utf-8")'
                        self.assertIn(original, code)
                        title = '# ' + expected['title'] + '\n'
                        first = '## ' + expected['ordered_headings'][0]
                        before, after = title + '\n' + first, title + gap + first
                        path.write_text(code.replace(original,
                            f'args.output.write_text(result.replace({before!r}, {after!r}, 1), encoding="utf-8")'))
                    completed, verdict, evaluated, _ = self.protected_run('doc', stage, mutation=mutate)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(verdict['checks'], [{'id': 'document-content', 'status': 'PASS'}])
                    self.assertEqual(verdict['errors'], [])
                    self.assertEqual(evaluated['status'], 'PASS')

    def test_doc_blank_line_variations_pass_resource_check(self):
        transformations = {
            'remove_blank_lines': '"\\n".join(line for line in result.splitlines() if line.strip()) + "\\n"',
            'add_whitespace_lines': 'result.replace("\\n", "\\n \\t\\n\\n")',
        }
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            for name, expression in transformations.items():
                with self.subTest(stage=stage, whitespace=name):
                    def mutate(product, protected):
                        path = product/'tools/render.py'
                        code = path.read_text()
                        original = 'args.output.write_text(result, encoding="utf-8")'
                        self.assertIn(original, code)
                        path.write_text(code.replace(original,
                            f'args.output.write_text({expression}, encoding="utf-8")'))
                    completed, verdict, evaluated, _ = self.protected_run('doc', stage, mutation=mutate)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(verdict['checks'][0]['status'], 'PASS')
                    self.assertEqual(verdict['errors'], [])
                    self.assertEqual(evaluated['status'], 'PASS')

    def test_doc_missing_resource_scratch_remains_infrastructure_error(self):
        completed, verdict, evaluated, _ = self.protected_run('doc', 'v2',
            environment={'FOUNDRY_SCRATCH_DIR': str(self.root/'absent-scratch')})
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn('failure_kind', verdict)
        self.assertEqual(verdict['checks'][0]['status'], 'ERROR')
        self.assertFalse(evaluated['automatic_retry_allowed'])

    def test_doc_cli_oserror_remains_infrastructure_error(self):
        for error, message, filename in (
                ('ENOSPC', 'scratch has no space', 'args.output'),
                ('ENOSPC', 'product volume has no space', 'args.root / "config.json"'),
                ('EACCES', 'product input permission denied', 'args.root / "config.json"')):
            with self.subTest(error=error, filename=filename):
                def unavailable(product, protected):
                    path = product/'tools/render.py'
                    code = path.read_text()
                    original = 'args.output.write_text(result, encoding="utf-8")'
                    self.assertIn(original, code)
                    path.write_text(code.replace(original,
                        f'import errno; raise OSError(errno.{error}, {message!r}, str({filename}))'))
                completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=unavailable)
                self.assertEqual(completed.returncode, 1)
                self.assertNotIn('failure_kind', verdict)
                self.assertEqual(verdict['checks'][0]['status'], 'ERROR')
                self.assertIn(message, ''.join(verdict['errors']))
                self.assertFalse(evaluated['automatic_retry_allowed'])

    def test_doc_cli_product_path_read_errors_are_repairable(self):
        for read_path in ('missing-config.json', 'config.json/child', 'data'):
            with self.subTest(read_path=read_path):
                def wrong_read_path(product, protected):
                    # Keep declared inputs intact. Only the product CLI's read
                    # path is wrong; relative filenames use its actual cwd.
                    self.assertTrue((product/'config.json').is_file())
                    self.assertTrue((product/'data/notes.json').is_file())
                    self.assertTrue((product/'data/sources.json').is_file())
                    path = product/'tools/render.py'
                    code = path.read_text()
                    self.assertIn('read("config.json")', code)
                    code = code.replace('(args.root / name)', 'Path(name)')
                    path.write_text(code.replace('read("config.json")', f'read({read_path!r})'))
                completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=wrong_read_path)
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(verdict.get('failure_kind'), 'ASSERTION', verdict)
                self.assertEqual(verdict['checks'][0]['status'], 'FAIL')
                self.assertEqual(verdict['errors'], [])
                self.assertEqual(evaluated['failure_domain'], 'BUSINESS_ASSERTION')
                self.assertTrue(evaluated['automatic_retry_allowed'])

    def test_doc_cli_scratch_path_read_errors_are_infrastructure(self):
        reads = (
            '(args.output.parent / "missing-input").read_text()',
            '(args.output.parent / "read-parent.txt").write_text("fixture"); '
            '(args.output.parent / "read-parent.txt" / "child").read_text()',
            'args.output.parent.read_text()',
        )
        for expression in reads:
            with self.subTest(expression=expression):
                def scratch_read(product, protected):
                    path = product/'tools/render.py'
                    code = path.read_text()
                    original = 'args.output.write_text(result, encoding="utf-8")'
                    self.assertIn(original, code)
                    path.write_text(code.replace(original, expression))
                completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=scratch_read)
                self.assertEqual(completed.returncode, 1)
                self.assertNotIn('failure_kind', verdict)
                self.assertEqual(verdict['checks'][0]['status'], 'ERROR')
                self.assertFalse(evaluated['automatic_retry_allowed'])

    def test_doc_cli_unattributed_path_error_is_infrastructure(self):
        def unattributed(product, protected):
            path = product/'tools/render.py'
            original = 'args.output.write_text(result, encoding="utf-8")'
            path.write_text(path.read_text().replace(original,
                'import errno; raise FileNotFoundError(errno.ENOENT, "unattributed read failure")'))
        completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=unattributed)
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn('failure_kind', verdict)
        self.assertEqual(verdict['checks'][0]['status'], 'ERROR')
        self.assertIn('unattributed read failure', ''.join(verdict['errors']))
        self.assertFalse(evaluated['automatic_retry_allowed'])

    def test_doc_cli_terminated_child_is_infrastructure(self):
        def terminate_self(product, protected):
            path = product/'tools/render.py'
            original = 'args.output.write_text(result, encoding="utf-8")'
            path.write_text(path.read_text().replace(original,
                'import os, signal; os.kill(os.getpid(), signal.SIGTERM)'))
        completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=terminate_self)
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn('failure_kind', verdict)
        self.assertEqual(verdict['checks'][0]['status'], 'ERROR')
        self.assertIn('terminated by a signal', ''.join(verdict['errors']))
        self.assertFalse(evaluated['automatic_retry_allowed'])

    def test_doc_business_assertion_and_infrastructure_error_stay_distinct(self):
        def wrong_content(product, protected):
            (product/'data/notes.json').write_text('[]')
        completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=wrong_content)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(verdict['failure_kind'], 'ASSERTION')
        self.assertEqual(evaluated['failure_domain'], 'BUSINESS_ASSERTION')
        self.assertTrue(evaluated['automatic_retry_allowed'])

    def test_missing_checker_dependency_is_not_product_repair(self):
        def missing_expected(product, protected):
            (protected/'expectations/doc-v2.json').unlink()
        completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=missing_expected)
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn('failure_kind', verdict)
        self.assertFalse(evaluated['automatic_retry_allowed'])
        self.assertEqual(verdict['checks'], [{'id': 'document-content', 'status': 'ERROR'}])

    def test_malformed_target_contracts_are_repairable_business_failures(self):
        cases = [
            ('doc', 'config.json', b'{'),
            ('doc', 'config.json', b'{}'),
            ('doc', 'tools/render.py', b'def render(:\n'),
            ('doc', 'tools/render.py', b'def render(*args): return ""\n'),
            ('doc', 'tools/render.py', b'placeholder = True\n'),
            ('doc', 'data/notes.json', b'\xff'),
            ('api', 'config.json', b'{'),
            ('api', 'config.json', b'{}'),
            ('api', 'tools/service.py', b'def response(:\n'),
            ('api', 'tools/service.py', b'placeholder = True\n'),
            ('api', 'tools/client.py', b'placeholder = True\n'),
            ('api', 'data/items.json', b'\xff'),
        ]
        for kind, name, content in cases:
            with self.subTest(kind=kind, name=name, content=content):
                def mutate(product, protected):
                    (product/name).write_bytes(content)
                completed, verdict, evaluated, _ = self.protected_run(kind, 'v2', mutation=mutate)
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(verdict['failure_kind'], 'ASSERTION')
                self.assertEqual(verdict['errors'], [])
                self.assertEqual(evaluated['failure_domain'], 'BUSINESS_ASSERTION')
                self.assertTrue(evaluated['automatic_retry_allowed'])
                if kind == 'api':
                    self.assertFalse(verdict['services_started'])
                    self.assertTrue(verdict['services_stopped'])

    def test_protected_dependency_errors_remain_infrastructure_failures(self):
        for name, content in [('expectations/doc-v2.json', b'{'),
                              ('expectations/doc-v2.json', b'{}'),
                              ('check_mechanisms.py', b'def broken(:\n'),
                              ('check_mechanisms.py', b'raise AssertionError("protected input error")\n')]:
            with self.subTest(name=name, content=content):
                def mutate(product, protected):
                    path = protected/name
                    path.chmod(0o600)
                    path.write_bytes(content)
                completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=mutate)
                self.assertEqual(completed.returncode, 1)
                self.assertNotIn('failure_kind', verdict)
                self.assertEqual(verdict['checks'][0]['status'], 'ERROR')
                self.assertFalse(evaluated['automatic_retry_allowed'])

    def test_user_notes_preserve_exact_bytes_including_line_endings(self):
        def crlf_notes(product, protected):
            notes = product/'USER_NOTES.md'
            notes.write_bytes(notes.read_bytes().replace(b'\n', b'\r\n'))
        completed, verdict, evaluated, _ = self.protected_run('doc', 'v2', mutation=crlf_notes)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(verdict['failure_kind'], 'ASSERTION')
        self.assertEqual(verdict['diagnostic'], 'user notes changed')
        self.assertTrue(evaluated['automatic_retry_allowed'])

    def test_service_startup_shape_error_is_not_target_repair(self):
        def startup_error(product, protected):
            path = product/'tools/service.py'
            path.write_text(path.read_text().replace('return ThreadingHTTPServer(("127.0.0.1", 0), Handler)',
                                                     'raise AttributeError("service startup unavailable")'))
        completed, verdict, evaluated, _ = self.protected_run('api', 'v2', mutation=startup_error)
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn('failure_kind', verdict)
        self.assertEqual(verdict['checks'][0]['status'], 'ERROR')
        self.assertFalse(evaluated['automatic_retry_allowed'])

    def test_api_success_report_includes_real_cleanup(self):
        completed, verdict, evaluated, _ = self.protected_run('api', 'v1')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(verdict['services_started'])
        self.assertTrue(verdict['services_stopped'])
        self.assertEqual(evaluated['status'], 'PASS')

    def test_api_http_assertion_preserves_cleanup_observation(self):
        def all_200(product, protected):
            path = product/'tools/service.py'
            path.write_text(path.read_text().replace('self.send_response(status)', 'self.send_response(200)'))
        completed, verdict, evaluated, _ = self.protected_run('api', 'v2', mutation=all_200)
        self.assertEqual(completed.returncode, 1)
        self.assertTrue(verdict['services_started'])
        self.assertTrue(verdict['services_stopped'])
        self.assertEqual(evaluated['failure_domain'], 'BUSINESS_ASSERTION')
        self.assertEqual(verdict['checks'], [{'id': 'api-contract', 'status': 'FAIL'}, {'id': 'owned-service-cleanup', 'status': 'PASS'}])

    def test_api_cleanup_exception_is_infrastructure_not_assertion(self):
        def cleanup_error(product, protected):
            path = product/'tools/service.py'
            code = path.read_text()
            original = 'return ThreadingHTTPServer(("127.0.0.1", 0), Handler)'
            replacement = '''server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    original_close = server.server_close
    def fail_after_close():
        original_close()
        raise RuntimeError("cleanup observation failed")
    server.server_close = fail_after_close
    return server'''
            self.assertIn(original, code)
            path.write_text(code.replace(original, replacement))
        completed, verdict, evaluated, _ = self.protected_run('api', 'v3', mutation=cleanup_error)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(verdict['services_stopped'])
        self.assertNotIn('failure_kind', verdict)
        self.assertFalse(evaluated['automatic_retry_allowed'])
        self.assertTrue(all(row['status'] == 'ERROR' for row in verdict['checks']))


if __name__ == '__main__':
    unittest.main()
