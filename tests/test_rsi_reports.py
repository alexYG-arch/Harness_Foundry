"""Generic report handoff tests; no active database, model or business execution."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from harness_foundry_factory.rsi_cases import write_case, read_json
from harness_foundry_factory.rsi_reports import reconstruct, query, read_source
from harness_foundry_factory.rsi_delivery import prepare_delivery

ROOT = Path(__file__).resolve().parents[1]


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.put('evidence.json', {'version': '1', 'status': 'PASS'})
        self.baseline = self.put('base.json', {'schema_version': 'REPORT_BASELINE_V1', 'version': '1',
            'items': [self.item('ok'), self.item('pending', 'NOT_RUN'), self.item('failed', 'FAIL')]})
        self.request = {'schema_version': 'REPORT_HANDOFF_V1', 'report_id': 'generic-task',
                        'baseline': self.baseline, 'deltas': []}

    def put(self, name, doc, version='1'):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps(doc, ensure_ascii=False) + '\n').encode() if not isinstance(doc, bytes) else doc
        path.write_bytes(raw)
        return {'path': name, 'version': version, 'sha256': hashlib.sha256(raw).hexdigest()}

    def item(self, ident, status='PASS', **extra):
        return {'id': ident, 'condition': 'Original requirement ' + ident,
                'reported_status': status, 'facts': ['recorded observation'],
                'interpretations': ['unverified explanation'], 'limits': ['selected scope'],
                'pending_checks': [], 'depends_on': [], 'conditions': {'mode': 'offline'},
                'source_refs': [deepcopy(self.evidence)], **extra}

    def delta(self, updates=(), affected=(), version='2'):
        ref = self.put('delta-' + version + '.json', {'schema_version': 'REPORT_DELTA_V1',
            'version': version, 'reason': 'Changed relevant input; other evidence unchanged',
            'affected_ids': list(affected), 'updates': list(updates)}, version)
        self.request['deltas'].append(ref)
        return ref

    def view(self):
        return reconstruct(self.request, self.root)

    def rows(self):
        return {r['item']['id']: r for r in self.view()['items']}

    def test_baseline_preserves_facts_limits_unknowns_and_has_no_authority(self):
        view = self.view(); rows = self.rows()
        self.assertEqual(view['original_total'], 3)
        self.assertEqual(rows['ok']['reuse_assessment'], 'SCOPED_REUSE_CANDIDATE')
        self.assertEqual(rows['pending']['item']['reported_status'], 'NOT_RUN')
        self.assertEqual(rows['failed']['item']['reported_status'], 'FAIL')
        self.assertNotEqual(rows['ok']['item']['facts'], rows['ok']['item']['interpretations'])
        for key in ('acceptance_verified', 'budget_modified', 'commands_executed'):
            self.assertFalse(view[key])

    def test_delta_does_not_drop_unmentioned_or_affected_old_work(self):
        self.delta([self.item('ok', 'ERROR')], ['ok', 'pending'])
        rows = self.rows()
        self.assertEqual(set(rows), {'ok', 'pending', 'failed'})
        self.assertEqual(rows['ok']['item']['reported_status'], 'ERROR')
        self.assertNotIn('AFFECTED_WITHOUT_NEW_OBSERVATION', rows['ok']['review_reasons'])
        self.assertIn('AFFECTED_WITHOUT_NEW_OBSERVATION', rows['pending']['review_reasons'])
        self.assertEqual(rows['failed']['item']['reported_status'], 'FAIL')

    def test_historical_unverified_dependency_prevents_reuse_of_unchanged_pass(self):
        self.delta([self.item('ok', depends_on=['pending'])])
        self.assertIn('UNRESOLVED_DEPENDENCY:pending', self.rows()['ok']['review_reasons'])
        self.assertEqual(self.rows()['ok']['item']['reported_status'], 'PASS')

    def test_dependency_chain_cycle_and_missing_are_explicit_not_execution(self):
        self.delta([self.item('ok', depends_on=['later']), self.item('later', depends_on=['failed']),
                    self.item('cycle', depends_on=['cycle']), self.item('missing', depends_on=['absent'])])
        rows = self.rows()
        self.assertIn('UNRESOLVED_DEPENDENCY:failed', rows['ok']['review_reasons'])
        self.assertIn('CYCLIC_DEPENDENCY:cycle', rows['cycle']['review_reasons'])
        self.assertIn('MISSING_DEPENDENCY:absent', rows['missing']['review_reasons'])
        self.assertFalse(self.view()['commands_executed'])

    def test_condition_change_and_new_item_keep_original_denominator_and_locator(self):
        self.delta([self.item('ok', condition='New reviewed requirement'), self.item('new', 'SKIP')])
        view = self.view(); rows = self.rows()
        self.assertEqual((view['original_total'], view['total']), (3, 4))
        self.assertEqual(rows['ok']['original_condition'], 'Original requirement ok')
        self.assertEqual(rows['ok']['provenance']['pointer'], '/updates/0')
        self.assertIn('BASELINE_CONDITIONS_CHANGED', rows['ok']['review_reasons'])
        self.assertEqual(rows['new']['item']['reported_status'], 'SKIP')

    def test_context_or_limit_changes_do_not_reuse_unchanged_old_pass(self):
        for extra in ({'conditions': {'mode': 'online'}}, {'limits': ['different scope']}):
            with self.subTest(extra=extra):
                self.request['deltas'] = []
                self.delta([self.item('ok', **extra)])
                self.assertIn('BASELINE_CONDITIONS_CHANGED', self.rows()['ok']['review_reasons'])
                self.assertEqual(self.rows()['ok']['item']['reported_status'], 'PASS')

    def test_missing_single_source_preserves_known_failure_and_other_rows(self):
        specific = self.put('private/source.json', b'ERROR')
        self.delta([self.item('failed', 'ERROR', source_refs=[specific])])
        (self.root/specific['path']).unlink()
        rows = self.rows()
        self.assertEqual(rows['failed']['item']['reported_status'], 'ERROR')
        self.assertEqual(rows['failed']['source_checks'][0]['binding'], 'UNAVAILABLE')
        self.assertEqual(rows['ok']['reuse_assessment'], 'SCOPED_REUSE_CANDIDATE')
        self.assertEqual(rows['failed']['item']['source_refs'], [specific])

    def test_changed_source_and_restoration_are_new_views_old_evidence_unchanged(self):
        old = self.view(); dest = self.root/'old-result.json'; write_case(old, dest); frozen = dest.read_bytes()
        original = (self.root/'evidence.json').read_bytes()
        (self.root/'evidence.json').write_bytes(b'other')
        changed = self.view()
        self.assertNotEqual(changed['view_id'], old['view_id'])
        self.assertEqual(changed['items'][0]['source_checks'][0]['binding'], 'CHANGED')
        (self.root/'evidence.json').write_bytes(original)
        self.assertEqual(self.view(), old)
        self.assertEqual(dest.read_bytes(), frozen)

    def test_corrupted_delta_keeps_prior_known_results_and_marks_partial(self):
        ref = self.delta([self.item('failed', 'PASS')])
        (self.root/ref['path']).write_bytes(b'{corrupt')
        rows = self.rows(); view = self.view()
        self.assertEqual(rows['failed']['item']['reported_status'], 'FAIL')
        self.assertEqual(view['reconstruction'], 'PARTIAL')
        self.assertEqual(view['history_gaps'][0]['binding'], 'CHANGED')
        self.assertTrue(all('INCOMPLETE_HISTORY' in r['review_reasons'] for r in rows.values()))

    def test_unreadable_baseline_does_not_invent_original_total_or_discard_delta(self):
        self.delta([self.item('known', 'ERROR')])
        (self.root/'base.json').unlink()
        view = self.view()
        self.assertIsNone(view['original_total']); self.assertEqual(view['reconstruction'], 'PARTIAL')
        self.assertEqual(view['items'][0]['item']['reported_status'], 'ERROR')

    def test_bound_but_invalid_json_or_version_keeps_gap(self):
        for raw in (b'{"version":"1","version":"1"}', b'{"version":"wrong"}', b'{bad'):
            with self.subTest(raw=raw):
                self.request['baseline'] = self.put('base.json', raw)
                self.assertEqual(self.view()['inputs'][0]['binding'], 'UNAVAILABLE')

    def test_acceptance_reference_missing_never_becomes_acceptance_or_reuse(self):
        ref = self.put('accepted.json', b'original accepted record')
        self.request['baseline_acceptance_ref'] = ref
        self.assertFalse(self.view()['acceptance_verified'])
        (self.root/'accepted.json').unlink()
        self.assertIn('BASELINE_ACCEPTANCE_UNRESOLVED', self.rows()['ok']['review_reasons'])

    def test_declared_contradiction_pending_checks_and_no_source_stay_visible(self):
        self.delta([self.item('ok', contradictions=['A conflicts with B']),
                    self.item('later', pending_checks=['check environment']),
                    self.item('unsupported', source_refs=[])])
        rows = self.rows()
        self.assertIn('DECLARED_CONTRADICTION', rows['ok']['review_reasons'])
        self.assertIn('PENDING_CHECKS', rows['later']['review_reasons'])
        self.assertIn('NO_BOUND_EVIDENCE', rows['unsupported']['review_reasons'])

    def test_dependency_resolution_uses_new_observation_not_old_repeated_status(self):
        self.delta([self.item('ok', depends_on=['pending'])], ['pending'])
        self.assertEqual(self.rows()['ok']['reuse_assessment'], 'REVIEW_REQUIRED')
        self.delta([self.item('pending')], version='3')
        self.assertEqual(self.rows()['ok']['reuse_assessment'], 'SCOPED_REUSE_CANDIDATE')
        self.assertFalse(self.view()['acceptance_verified'])

    def test_duplicate_delta_and_duplicate_item_are_not_double_counted(self):
        ref = self.delta()
        self.request['deltas'].append(ref)
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.view()
        self.request['deltas'] = []
        self.delta([self.item('ok'), self.item('ok')])
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.view()

    def test_unknown_affected_id_rejected_when_history_complete(self):
        self.delta(affected=['typo'])
        with self.assertRaisesRegex(ValueError, 'unknown affected'): self.view()

    def test_custom_fields_assertions_and_original_budget_are_lossless(self):
        extra = {'budget': {'used': 4, 'remaining': 2}, 'assertions': ['positive', 'negative'],
                 'project_data': {'nullable': None, 'ordered': [2, 1, True]}}
        self.delta([self.item('ok', **extra)])
        for key, value in extra.items(): self.assertEqual(self.rows()['ok']['item'][key], value)
        self.assertFalse(self.view()['budget_modified'])

    def test_pagination_is_explicit_and_details_restore_omitted_fields(self):
        view = self.view(); one = query(view, limit=1)
        self.assertEqual(one['next_offset'], 1); self.assertFalse(one['all_items_returned'])
        self.assertIn('facts', one['items'][0]['omitted_fields'])
        two = query(view, offset=1, limit=2, view_id=one['view_id'], details=True)
        self.assertTrue(two['selection_complete']); self.assertFalse(two['all_items_returned'])
        self.assertIn('facts', two['items'][0]['item'])
        self.assertEqual(len(query(view, limit=100000, details=True)['items']), 3)

    def test_changed_view_invalidates_continuation_without_mixing_pages(self):
        prior = query(self.view(), limit=1)
        (self.root/'evidence.json').unlink()
        result = query(self.view(), offset=1, view_id=prior['view_id'])
        self.assertFalse(result['continuation_valid']); self.assertEqual(result['items'], [])
        self.assertEqual(result['diagnostic'], 'VIEW_CHANGED_RESTART_QUERY')

    def test_filters_by_id_condition_field_and_source(self):
        view = self.view()
        self.assertEqual(query(view, item_id='ok')['matches'], 1)
        self.assertEqual(query(view, field='reported_status', value='FAIL')['matches'], 1)
        self.assertEqual(query(view, conditions={'mode': 'online'})['matches'], 0)
        self.assertEqual(query(view, source='evidence.json')['matches'], 3)
        self.assertEqual(query(view, field='missing')['matches'], 0)

    def test_field_filter_keeps_null_distinct_from_omitted_and_false_from_zero(self):
        self.delta([self.item('ok', optional=None), self.item('failed', 'FAIL', optional=False),
                    self.item('pending', 'NOT_RUN', optional=0)])
        view = self.view()
        self.assertEqual(query(view, field='optional')['matches'], 3)
        self.assertEqual(query(view, field='optional', value=None)['matches'], 1)
        self.assertEqual(query(view, field='optional', value=False)['matches'], 1)
        self.assertEqual(query(view, field='optional', value=0)['matches'], 1)

    def test_delivered_cli_filters_explicit_null(self):
        self.delta([self.item('ok', optional=None), self.item('failed', 'FAIL', optional=False)])
        path = self.root/'handoff.json'; path.write_text(json.dumps(self.request))
        out = self.root/'support'
        prepare_delivery(ROOT, {'version': '1', 'wiki': {'collections': []}}, self.root, out)
        result = self.root/'filtered.json'
        proc = subprocess.run([sys.executable, '-I', '-S', '-B', str(out/'tools/report_rsi_view.py'),
            'query', '--manifest', str(path), '--field', 'optional', '--value', 'null',
            '--output', str(result)], cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = read_json(result.read_text())
        self.assertEqual(data['matches'], 1); self.assertEqual(data['items'][0]['item']['id'], 'ok')

    def test_existing_case_handoff_reuses_report_reference_without_reimport_or_budget_change(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'report_case_handoff', ROOT/'examples/capability-adapters/rsi_handoff.py')
        H = importlib.util.module_from_spec(spec); spec.loader.exec_module(H)
        view_path = self.root/'view.json'; write_case(query(self.view(), details=True), view_path)
        original = {'status': 'FAIL', 'budget': {'used': 3, 'remaining': 2}}
        self.put('controller-report.json', original)
        request = {'enabled': True, 'identity': {'project': 'generic', 'task': 'task', 'issue': 'issue'},
            'phase': 'return', 'case': {'case_id': 'case', 'goal': 'retain original observations',
            'sources': [{'source_id': 'raw', 'path': 'controller-report.json', 'kind': 'FOUNDRY_REPORT'}]},
            'references': [{'role': 'current-report-view', 'path': 'view.json'}]}
        first = H.capture(request, self.root, self.root/'handoff')
        with patch.object(H.rsi_cases, 'import_case', side_effect=AssertionError('no reimport')):
            second = H.capture(request, self.root, self.root/'handoff')
        self.assertTrue(second['reused']); self.assertEqual(first['directory'], second['directory'])
        data = read_json((Path(second['directory'])/'case.json').read_text())
        self.assertEqual(data['sources'][0]['document'], original)
        self.assertEqual(second['references'][0]['observation']['sha256'],
                         hashlib.sha256(view_path.read_bytes()).hexdigest())
        self.assertFalse(second['budget_modified']); self.assertFalse(second['commands_executed'])
        alias = self.root/'parent-alias'; alias.symlink_to(self.root.resolve(), target_is_directory=True)
        third = H.capture(request, self.root, alias/'handoff')
        self.assertTrue(third['reused']); self.assertEqual(third['directory'], first['directory'])

    def test_no_history_full_text_recursion_in_multiple_deltas(self):
        prior = (self.root/'base.json').read_bytes()
        for n in range(2, 7):
            self.delta([self.item('ok', facts=['new observation ' + str(n)])], version=str(n))
        view = self.view()
        self.assertEqual(len(view['inputs']), 6)
        self.assertEqual(len(view['items']), 3)
        self.assertFalse(any('document' in r for r in view['inputs']))
        self.assertEqual((self.root/'base.json').read_bytes(), prior)

    def test_byte_paging_preserves_multibyte_and_binary_originals(self):
        raw = '汉A🙂'.encode() + b'\xff\n'
        ref = self.put('raw.bin', raw)
        chunks = []; offset = 0
        while True:
            part = read_source(self.root, ref, offset=offset, length=2)
            self.assertEqual(part['binding'], 'MATCH')
            self.assertFalse(part['complete_read'])
            chunks.append(base64.b64decode(part['bytes_base64']))
            if part['next_offset'] is None: break
            offset = part['next_offset']
        self.assertEqual(b''.join(chunks), raw)
        whole = read_source(self.root, ref, length=100)
        self.assertTrue(whole['complete_read']); self.assertIsNone(whole['text'])

    def test_source_changed_unavailable_and_empty_have_distinct_results(self):
        ref = self.put('empty', b'')
        empty = read_source(self.root, ref)
        self.assertTrue(empty['complete_read']); self.assertEqual(empty['text'], '')
        (self.root/'empty').write_bytes(b'different')
        self.assertEqual(read_source(self.root, ref)['binding'], 'CHANGED')
        (self.root/'empty').unlink()
        self.assertEqual(read_source(self.root, ref)['binding'], 'UNAVAILABLE')

    def test_legal_alias_and_in_root_link_work_without_following_undeclared_files(self):
        alias = self.root/'alias'; alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(reconstruct(self.request, alias), self.view())
        (self.root/'linked').symlink_to(self.root/'evidence.json')
        ref = {**self.evidence, 'path': 'linked'}
        self.assertEqual(read_source(self.root, ref)['binding'], 'MATCH')
        outside = self.root.parent/'not-authorized'
        (self.root/'escape').symlink_to(outside)
        with patch.object(Path, 'open', side_effect=AssertionError('must not read outside')):
            self.assertEqual(read_source(self.root, {**ref, 'path': 'escape'})['binding'], 'UNAVAILABLE')

    def test_invalid_paging_does_not_mutate_materials(self):
        raw = (self.root/'base.json').read_bytes()
        for kwargs in ({'limit': 0}, {'offset': -1}, {'limit': True}):
            with self.assertRaises(ValueError): query(self.view(), **kwargs)
        with self.assertRaises(ValueError): read_source(self.root, self.evidence, length=0)
        self.assertEqual((self.root/'base.json').read_bytes(), raw)

    def test_output_never_overwrites_or_reexecutes_on_retrieval(self):
        output = self.root/'result.json'; view = self.view()
        write_case(view, output); before = output.read_bytes()
        with self.assertRaises(FileExistsError): write_case(self.view(), output)
        self.assertEqual(output.read_bytes(), before)

    def test_relocated_selected_delivery_runs_real_cli_without_development_imports(self):
        output = self.root/'support'
        receipt = prepare_delivery(ROOT, {'version': '1', 'wiki': {'collections': []}},
                                   self.root, output)
        moved = self.root/'new support 目录'; output.rename(moved)
        request_path = self.root/'handoff.json'; request_path.write_text(json.dumps(self.request))
        for number in (1, 2):
            result = self.root/('page-' + str(number) + '.json')
            proc = subprocess.run([sys.executable, '-I', '-S', '-B', str(moved/'tools/report_rsi_view.py'),
                'query', '--manifest', str(request_path), '--details', '--output', str(result)],
                cwd=self.root, env={**os.environ, 'PYTHONPATH': '/missing/development'},
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(read_json(result.read_text()), query(self.view(), details=True))
        self.assertIn('src/harness_foundry_factory/rsi_reports.py', receipt['files'])
        self.assertIn('docs/RSI_REPORT_HANDOFF.md', receipt['files'])
        self.assertFalse((moved/'base.json').exists())
        self.assertFalse(receipt['budget_modified'])
