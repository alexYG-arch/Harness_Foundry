"""Request/snapshot/helper regressions, not real business or host acceptance."""

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

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_runtime import (
    BuildController, _validate_scope, approve_build_authorization,
    prepare_build_authorization, record_source_snapshot,
)
from harness_foundry_factory.source_intake import load_local_sources, validate_requirement_source_bindings
from harness_foundry_factory.store import ControlEventStore
from harness_foundry_factory.verification_resources import validate_resources
from harness_foundry_factory.verification_snapshot import snapshot_verifier
from test_build_resources import DurableResourceFixtureRunner
from tests.build_review_fixture import reviewed_document


EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'harness-composition-upgrade'
SPEC = importlib.util.spec_from_file_location('r3_business_requests', EXAMPLE / 'integration/business_requests.py')
REQUESTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REQUESTS)


class HarnessBusinessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = self.root / 'business'
        shutil.copytree(EXAMPLE / 'business', self.fixture)
        self.helpers = self.root / 'helpers'
        shutil.copytree(EXAMPLE / 'helpers', self.helpers)
        self.document = self.root / 'reviewed-build.md'
        self.document.write_bytes(b'# Separate business contract\r\nOriginal input and review scope.\r\n')
        self.verifier = self.root / 'verifier'
        self.verifier.mkdir()
        shutil.copyfile(EXAMPLE / 'verifier/check_business.py', self.verifier / 'check_business.py')

    def bindings(self, group):
        directory = REQUESTS.GROUPS[group.replace('_', '-')]
        return {'program_id': 'R3-BUSINESS-TEST', 'requirement_path': str(self.document),
                'workspace_root': str(self.root / 'workspace'), 'verification_root': str(self.verifier),
                'resource_root': str(self.root / 'resources'), 'group_root': str(self.fixture / directory),
                'python_executable': sys.executable, 'python_read_roots': [], 'codex_executable': sys.executable,
                'model': 'caller-selected-test-model', 'max_attempts': 2, 'max_task_attempts': 2,
                'command_timeout_seconds': 60, 'expires_at': '2099-01-01T00:00:00Z'}

    def reviewed_bindings(self, group, version):
        bindings = self.bindings(group)
        manifest = json.loads((Path(bindings['group_root']) / 'manifest.json').read_text())
        names = (manifest['live_outputs'] if group == 'market-live' else manifest['outputs'] +
                 (manifest['v2_additional_outputs'] if version == 'v2' else []))
        prior = self.root / 'prior-outputs'
        prior.mkdir(exist_ok=True)
        host = self.root / 'host-evidence'
        (host / 'reviewed-output').mkdir(parents=True, exist_ok=True)
        (host / 'evidence').mkdir(exist_ok=True)
        for name in names:
            # Bytes deliberately are not accepted business answers. These tests
            # exercise declared copy and snapshot behavior, not semantic truth.
            data = ('unaccepted test bytes for ' + name + '\n').encode()
            (prior / name).write_bytes(data)
            (host / 'reviewed-output' / name).write_bytes(data)
        (host / 'workflow.md').write_bytes((Path(bindings['group_root']) / manifest['workflows'][version]).read_bytes())
        (host / 'evidence/observation.txt').write_text('Synthetic test observation; actual host execution not run.\n')
        (host / 'review.json').write_text(json.dumps({
            'group': group, 'version': version, 'reviewer': 'test-only',
            'reviewed_outputs': 'reviewed-output', 'workflow_file': 'workflow.md',
            'observations': [{'id': 'workflow-execution', 'result': 'NOT_RUN', 'reason': 'test fixture only',
                              'evidence_refs': ['evidence/observation.txt']}]}))
        bindings.update(prior_outputs_root=str(prior), host_evidence_root=str(host),
                        apply_manifest=str(self.root / 'reuse.json'), helpers_root=str(self.helpers))
        return bindings, names

    def automatic_bindings(self, group, version):
        bindings = self.bindings(group)
        if version == 'v2':
            prior = self.root / 'prior-outputs'
            prior.mkdir(exist_ok=True)
            manifest = json.loads((Path(bindings['group_root']) / 'manifest.json').read_text())
            for name in manifest['outputs']:
                (prior / name).write_text('Actual previous test output with retained business decisions: ' + name)
            bindings['prior_outputs_root'] = str(prior)
        return bindings

    def validate_materials(self, materials):
        request, scope = materials['request'], materials['scope']
        compile_build_plan(request['requirement_ir'], request['plan'])
        captured = load_local_sources(Path(materials['preparation']['source_root']), materials['source_manifest'])
        validate_requirement_source_bindings(request['requirement_ir'], captured)
        self.assertEqual(request['requirement_ir']['atoms'][0]['text_or_lossless_paraphrase'], captured['sources'][0]['text'])
        validate_resources(scope['verification_resources'], request['plan'], protected_paths=[
            scope['workspace_root'], scope['verification_root'], self.root / 'control.sqlite3', *scope['source_read_roots']])
        self.assertFalse((self.root / 'workspace').exists())
        self.assertFalse((self.root / 'control.sqlite3').exists())
        self.assertFalse((self.root / 'resources').exists())
        self.assertEqual(materials['preparation']['status'], 'MATERIALS_ONLY_NOT_APPROVED')
        self.assertIsNone(materials['preparation']['runtime_identity'])
        self.assertNotIn('document_review', request)
        self.assertNotIn('expected_revision', request)

    def prepare_verifier_inputs(self, materials):
        for row in materials['preparation']['verifier_inputs']:
            destination = self.verifier / row['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row['source'], destination)

    def test_all_fixed_groups_and_versions_compile_with_exact_input_scope(self):
        for group in ('prd-design', 'data-reasoning', 'market-research'):
            for version in ('v1', 'v2'):
                with self.subTest(group=group, version=version):
                    bindings = self.automatic_bindings(group, version)
                    materials = REQUESTS.build_materials(group, version, 'automatic', bindings)
                    self.validate_materials(materials)
                    wp = materials['request']['plan']['workpacks'][0]
                    self.assertEqual(wp['executor'], 'CODEX')
                    self.assertNotIn('local_argv', wp)
                    self.assertEqual(materials['scope']['model'], bindings['model'])
                    self.assertTrue(materials['scope']['allow_model_service'])
                    fixture = Path(bindings['group_root'])
                    manifest = json.loads((fixture / 'manifest.json').read_text())
                    reads = set(materials['scope']['source_read_roots'])
                    self.assertTrue({str(fixture / name) for name in manifest['inputs']} <= reads)
                    self.assertIn(str(fixture / manifest['workflows'][version]), reads)
                    for hidden in ('expected.json', 'counterexamples.json'):
                        self.assertFalse(any((fixture / hidden).is_relative_to(Path(root)) for root in reads))
                    expected = manifest['outputs'] + (manifest['v2_additional_outputs'] if version == 'v2' else [])
                    self.assertEqual([a['path'] for a in wp['artifacts']], ['outputs/' + name for name in expected])
                    self.assertNotIn('live-source-register.json', ' '.join(expected))

    def test_actual_selected_workflow_bytes_are_loaded_without_normalization(self):
        bindings = self.automatic_bindings('prd_design', 'v2')
        selected = Path(bindings['group_root']) / 'workflows/v2.md'
        selected.write_bytes(b'# Actual chosen workflow\r\nPreserve customized title.\r\n')
        materials = REQUESTS.build_materials('prd_design', 'v2', 'automatic', bindings)
        actual = selected.read_bytes().decode()
        self.assertEqual(materials['preparation']['workflow_text'], actual)
        self.assertIn(actual, materials['request']['plan']['workpacks'][0]['goal'])

    def test_reviewed_plans_only_reuse_declared_old_outputs(self):
        for group in REQUESTS.GROUPS:
            for version in ('v1', 'v2'):
                with self.subTest(group=group, version=version):
                    bindings, names = self.reviewed_bindings(group, version)
                    materials = REQUESTS.build_materials(group, version, 'reviewed', bindings)
                    self.validate_materials(materials)
                    wp = materials['request']['plan']['workpacks'][0]
                    self.assertEqual(wp['executor'], 'LOCAL')
                    self.assertEqual(wp['local_argv'][3], str(self.helpers / 'apply.py'))
                    self.assertFalse(materials['scope']['allow_model_service'])
                    self.assertIsNone(materials['scope']['model'])
                    self.assertEqual([row['path'] for row in materials['preparation']['apply_manifest']['files']],
                                     ['outputs/' + name for name in names])
                    self.assertEqual(wp['inputs'], [{'kind': 'SOURCE', 'id': 'BUILD-DOCUMENT'}])
                    self.assertEqual(wp['verification'][0]['argv'][-2:],
                                     ['--host-evidence', 'verifier://host-evidence/review.json'])
                    self.assertFalse(Path(bindings['apply_manifest']).exists())

    def test_all_prepared_scopes_validate_without_creating_a_program_or_target(self):
        for group in REQUESTS.GROUPS:
            for version in ('v1', 'v2'):
                phases = ['reviewed'] if group == 'market-live' else ['automatic', 'reviewed']
                for phase in phases:
                    with self.subTest(group=group, version=version, phase=phase):
                        bindings = (self.automatic_bindings(group, version) if phase == 'automatic' else
                                    self.reviewed_bindings(group, version)[0])
                        materials = REQUESTS.build_materials(group, version, phase, bindings)
                        self.validate_materials(materials)
                        self.prepare_verifier_inputs(materials)
                        if phase == 'reviewed':
                            Path(bindings['apply_manifest']).write_text(json.dumps(materials['preparation']['apply_manifest']))
                        _validate_scope(SimpleNamespace(database_path=self.root / 'control.sqlite3'),
                                        materials['request']['plan'], materials['scope'])
                        if phase == 'reviewed':
                            Path(bindings['apply_manifest']).unlink()
                        self.assertFalse((self.root / 'workspace').exists())
                        self.assertFalse((self.root / 'control.sqlite3').exists())

    def test_v2_reads_actual_prior_outputs_and_ordinary_handoff_without_inheriting_identity(self):
        bindings = self.automatic_bindings('prd-design', 'v2')
        handoff = self.root / 'handoff.md'
        handoff.write_text('Prior Program P-OLD and its readback live in the earlier control root; this is context only.\n')
        bindings['handoff_path'] = str(handoff)
        materials = REQUESTS.build_materials('prd-design', 'v2', 'automatic', bindings)
        self.validate_materials(materials)
        prior = Path(bindings['prior_outputs_root'])
        manifest = json.loads((Path(bindings['group_root']) / 'manifest.json').read_text())
        reads = materials['scope']['source_read_roots']
        self.assertTrue(all(str(prior / name) in reads for name in manifest['outputs']))
        self.assertNotIn(str(prior), reads)
        self.assertNotIn(str(prior / 'state-transitions.json'), reads)
        self.assertIn(str(handoff), reads)
        self.assertIn('actual prior v1 business outputs', materials['request']['plan']['workpacks'][0]['goal'])
        self.assertIsNone(materials['preparation']['accepted_A'])
        self.assertEqual(materials['request']['plan']['workpacks'][0]['inputs'], [{'kind': 'SOURCE', 'id': 'BUILD-DOCUMENT'}])
        del bindings['prior_outputs_root']
        with self.assertRaises(KeyError):
            REQUESTS.build_materials('prd-design', 'v2', 'automatic', bindings)
        v1 = REQUESTS.build_materials('prd-design', 'v1', 'automatic', self.bindings('prd-design'))
        self.assertNotIn('prior_outputs', v1['preparation'])
        self.assertIsNone(v1['preparation']['accepted_A'])
        bindings['prior_outputs_root'] = str(prior)
        with self.assertRaisesRegex(ValueError, 'do not invent prior'):
            REQUESTS.build_materials('prd-design', 'v1', 'automatic', bindings)

    def test_local_reuse_copies_bytes_and_can_resume_without_producer(self):
        bindings, names = self.reviewed_bindings('prd-design', 'v2')
        materials = REQUESTS.build_materials('prd-design', 'v2', 'reviewed', bindings)
        self.validate_materials(materials)
        Path(bindings['apply_manifest']).write_text(json.dumps(materials['preparation']['apply_manifest']))
        target = Path(bindings['workspace_root'])
        target.mkdir()
        argv = materials['request']['plan']['workpacks'][0]['local_argv']
        argv = [sys.executable, *argv[1:]]
        first = subprocess.run(argv, cwd=target, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        original = {name: (Path(bindings['prior_outputs_root']) / name).read_bytes() for name in names}
        self.assertEqual({name: (target / 'outputs' / name).read_bytes() for name in names}, original)
        second = subprocess.run(argv, cwd=target, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        report = json.loads((target / 'outputs/reuse-result.json').read_text())
        self.assertEqual({row['status'] for row in report['files']}, {'ALREADY_DESIRED'})
        self.assertEqual({name: (Path(bindings['prior_outputs_root']) / name).read_bytes() for name in names}, original)

    def test_protected_file_anchors_snapshot_fixture_and_host_inputs(self):
        bindings, _ = self.reviewed_bindings('data-reasoning', 'v2')
        materials = REQUESTS.build_materials('data-reasoning', 'v2', 'reviewed', bindings)
        self.validate_materials(materials)
        self.prepare_verifier_inputs(materials)
        snapshot = snapshot_verifier(SimpleNamespace(database_path=self.root / 'control.sqlite3'),
                                     materials['request']['plan'], materials['scope'])
        protected = Path(snapshot['runtime_root'])
        for row in materials['preparation']['verifier_inputs']:
            self.assertEqual((protected / row['path']).read_bytes(), Path(row['source']).read_bytes())
        self.assertIn('check_business.py', snapshot['files'])
        self.assertFalse((self.root / 'control.sqlite3').exists())
        original = (protected / 'business/data-reasoning/inputs/orders.csv').read_bytes()
        (self.fixture / 'data-reasoning/inputs/orders.csv').write_text('modified after preparation\n')
        self.assertEqual((protected / 'business/data-reasoning/inputs/orders.csv').read_bytes(), original)
        # Execute only the checker against absent test products. A real protected
        # snapshot must report a failed obligation, never fabricate acceptance.
        outputs = self.root / 'missing-products'
        outputs.mkdir()
        reports = self.root / 'reports'
        reports.mkdir()
        result = subprocess.run([sys.executable, '-I', '-B', str(protected / 'check_business.py'),
            '--group', 'data-reasoning', '--version', 'v2', '--phase', 'reviewed', '--target', str(outputs),
            '--fixture', str(protected / 'business/data-reasoning/manifest.json'),
            '--host-evidence', str(protected / 'host-evidence/review.json')], capture_output=True, text=True,
            env={**os.environ, 'FOUNDRY_VERIFIER_ROOT': str(protected), 'FOUNDRY_REPORT_DIR': str(reports),
                 'FOUNDRY_CASE_ID': 'TEST-CASE', 'FOUNDRY_COMMAND_ID': 'TEST-COMMAND'})
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = json.loads((reports / 'summary.json').read_text())
        self.assertEqual(report['checks'][0]['id'], 'business-reviewed')
        self.assertFalse(report['business_acceptance'])

    def test_missing_workflow_hidden_scope_and_live_automatic_are_not_materialized(self):
        bindings = self.bindings('prd-design')
        with self.assertRaisesRegex(ValueError, 'market-live'):
            REQUESTS.build_materials('market-live', 'v1', 'automatic', bindings)
        bindings['python_read_roots'] = [str(self.fixture)]
        with self.assertRaisesRegex(ValueError, 'independent business'):
            REQUESTS.build_materials('prd-design', 'v1', 'automatic', bindings)
        bindings['python_read_roots'] = []
        (self.fixture / 'prd-design/workflows/v1.md').unlink()
        with self.assertRaisesRegex(ValueError, 'missing declared input'):
            REQUESTS.build_materials('prd-design', 'v1', 'automatic', bindings)
        self.assertFalse((self.root / 'workspace').exists())

    def test_reviewed_failure_returns_once_and_fresh_review_preserves_old_evidence_and_usage(self):
        # Synthetic review and approvals only. Real subprocesses exercise the
        # controller handoff; no model, browser or native sandbox is qualified.
        bindings, names = self.reviewed_bindings('prd-design', 'v1')
        prior = Path(bindings['prior_outputs_root'])
        fixture = Path(bindings['group_root'])
        expected = json.loads((fixture / 'expected.json').read_text())
        (prior / 'traceability.json').write_text(json.dumps({
            'requirements': [{'id': row['id'], 'prd_section': row['id'],
                              'prototype_refs': [row['id']]} for row in expected['requirements']],
            'states': expected['required_states'], 'view_widths': [375, 1280],
            'customization': json.loads((fixture / 'inputs/user-customization.json').read_text())}))
        (prior / 'prd.md').write_text('Synthetic defect: offline save claims a confirmed reservation.\n')
        old_host = Path(bindings['host_evidence_root'])
        review = json.loads((old_host / 'review.json').read_text())
        obligations = ['workflow-execution', 'original-requirements', 'render-mobile-desktop',
                       'interactive-states', 'customization-preserved']
        review['observations'] = [{'id': key, 'result': 'FAIL' if key == 'original-requirements' else 'PASS',
            'reason': 'Synthetic review fixture for ' + key,
            'evidence_refs': ['evidence/observation.txt']} for key in obligations]
        for name in names:
            shutil.copyfile(prior / name, old_host / 'reviewed-output' / name)
        (old_host / 'review.json').write_text(json.dumps(review))
        old_bytes = {str(p.relative_to(old_host)): p.read_bytes() for p in old_host.rglob('*') if p.is_file()}

        def execute(selected, database):
            materials = REQUESTS.build_materials('prd-design', 'v1', 'reviewed', selected)
            self.assertEqual(materials['preparation']['advance_request'], {'advance_mode': 'ONE_ATTEMPT'})
            self.assertNotIn('codex_handoff', materials['preparation']['advance_request'])
            for row in materials['preparation']['verifier_inputs']:
                dest = Path(selected['verification_root']) / row['path']
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(row['source'], dest)
            Path(selected['apply_manifest']).write_text(json.dumps(materials['preparation']['apply_manifest']))
            store = ControlEventStore(database, storage_format='REVISION_V1')
            program = selected['program_id']
            def kwargs(key):
                return {'expected_revision': len(store.list_events(program)), 'idempotency_key': key,
                        'created_at': '2026-10-15T00:00:00+00:00'}
            request = materials['request']
            proposal = record_build_plan_proposal(store, request['requirement_ir'], request['plan'],
                document_review=reviewed_document(self.root, path=self.document, source_id='BUILD-DOCUMENT'),
                **kwargs('proposal'))
            source = record_source_snapshot(store, program, proposal['event_id'], self.root,
                                            materials['source_manifest'], **kwargs('source'))
            prepared = prepare_build_authorization(store, program, proposal['event_id'], source['event_id'],
                                                   materials['scope'], **kwargs('prepare'))
            approve_build_authorization(store, program, prepared['event_id'],
                human_message_ref='TEST-FIXTURE-ONLY-NOT-A-REAL-GRANT', **kwargs('approve'))
            runner = DurableResourceFixtureRunner()
            result = BuildController(store, program, runner=runner).advance(
                prepared['event_id'], **materials['preparation']['advance_request'])
            self.assertEqual(result['status'], 'BUILD_CONTROL_RETURNED', result)
            self.assertEqual(result['budget']['attempts_consumed'], 1)
            self.assertEqual([row['phase'] for row in runner.invocations], ['IMPLEMENTATION', 'VERIFICATION'])
            before_read = store.list_events(program)
            readback = read_build(database, program)
            self.assertEqual(read_build(database, program), readback)
            self.assertEqual(store.list_events(program), before_read)
            self.assertEqual(len(runner.invocations), 2, 'readback must not redispatch fixed REUSE')
            self.assertEqual(len(readback['attempts']), 1)
            return result, readback, before_read

        failed, old_readback, old_events = execute(bindings, self.root / 'failed.sqlite3')
        self.assertEqual(failed['attempt_status'], 'REJECTED')
        finding = old_readback['attempts'][0]['verification'][0]['result']
        self.assertEqual(finding['failure_domain'], 'BUSINESS_ASSERTION')
        self.assertTrue(finding['automatic_retry_allowed'], 'keep native classification; the host selects single-step')

        # Stand in for a separately authorized producer repair plus independent
        # re-review. The fixed REUSE task never receives a model repair prompt.
        (prior / 'prd.md').write_text('Synthetic corrected result: offline save remains an unconfirmed draft.\n')
        fresh = {**bindings, 'program_id': 'R3-REVIEW-FRESH',
                 'workspace_root': str(self.root / 'fresh-workspace'),
                 'verification_root': str(self.root / 'fresh-verifier'),
                 'resource_root': str(self.root / 'fresh-resources'),
                 'host_evidence_root': str(self.root / 'fresh-host'),
                 'apply_manifest': str(self.root / 'fresh-reuse.json')}
        new_host = Path(fresh['host_evidence_root'])
        shutil.copytree(old_host, new_host)
        for name in names:
            shutil.copyfile(prior / name, new_host / 'reviewed-output' / name)
        review['observations'][1]['result'] = 'PASS'
        review['observations'][1]['reason'] = 'Synthetic independent re-review after correction'
        (new_host / 'review.json').write_text(json.dumps(review))
        new_verifier = Path(fresh['verification_root'])
        new_verifier.mkdir()
        shutil.copyfile(EXAMPLE / 'verifier/check_business.py', new_verifier / 'check_business.py')
        passed, _, _ = execute(fresh, self.root / 'fresh.sqlite3')
        self.assertEqual(passed['attempt_status'], 'ACCEPTED')
        self.assertEqual(read_build(self.root / 'failed.sqlite3', bindings['program_id']), old_readback)
        self.assertEqual(ControlEventStore(self.root / 'failed.sqlite3', read_only=True,
            storage_format='REVISION_V1').list_events(bindings['program_id']), old_events)
        self.assertEqual({str(p.relative_to(old_host)): p.read_bytes() for p in old_host.rglob('*') if p.is_file()}, old_bytes)


if __name__ == '__main__':
    unittest.main()
