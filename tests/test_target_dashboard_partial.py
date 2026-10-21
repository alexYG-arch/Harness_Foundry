"""WP08 per-item read gaps and partial native bindings; engineering coverage only.

The new observer reads explicit records. Fixture changes below model independently
written reports, never an observer request to execute or replay business work.
"""

from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch

import test_capability_data as data_fixture
import test_capability_doc as doc_fixture
import test_target_dashboard as dashboard_fixture


TARGET = dashboard_fixture.TARGET


class TargetDashboardPartialTests(unittest.TestCase):
    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def dashboard(self):
        return self.fixture(dashboard_fixture.TargetDashboardTests)

    def states(self, projection):
        return {row['item_id']: row['state'] for row in projection['business']['items']}

    def save_report(self, path, report):
        path.write_text(json.dumps(report), encoding='utf-8')

    def report_with_state(self, fixture, state):
        report = deepcopy(fixture.report_data)
        report['status'] = 'CHECKS_PASS' if state == 'PASS' else 'CHECKS_FAILED'
        report['checks'][0]['status'] = state
        if state == 'FAIL':
            report['failure_kind'] = 'ASSERTION'
        elif state == 'ERROR':
            report['errors'] = ['Synthetic report infrastructure error']
        return report

    def add_second(self, fixture, report_name='second-report.json'):
        item = deepcopy(fixture.record_data['items'][0])
        item.update(item_id='SECOND', label='第二项', report=report_name,
                    evidence_ref='second-check')
        fixture.record_data['items'].append(item)
        fixture.record_data['steps'].append({'step_id': 'SECOND_CHECK',
            'label': '第二项独立检查', 'item_id': 'SECOND', 'phase': 'check'})
        fixture.save()
        return fixture.root / report_name

    def wait(self, observer, run_id, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = observer.snapshot(run_id)
            if predicate(snapshot):
                return snapshot
            time.sleep(.01)
        self.fail('expected per-item observer state was not collected')

    def no_dispatch(self):
        # Patch both execution surfaces while observing, including reconnection
        # and source recovery; the only writes are explicit fixture changes.
        return patch('subprocess.Popen', side_effect=AssertionError('observer must not dispatch'))

    def native_record(self, root, kind, report, paths, check_id):
        selection = dashboard_fixture.identity(run='native-partial-report')
        record = root / 'display.json'
        record.write_text(json.dumps({
            'selection': selection, 'scope_complete': True,
            'items': [{'item_id': 'NATIVE', 'label': '原生检查', 'format': kind,
                       'report': str(report), 'check_ids': [check_id],
                       'files': {key: {'path': str(path)} for key, path in paths.items()}}],
            'steps': [{'step_id': 'CHECK', 'label': '独立检查', 'item_id': 'NATIVE'}],
            'budget': {'attempts_consumed': 1, 'attempts_remaining': 2},
        }), encoding='utf-8')
        return record, selection

    def test_first_missing_item_preserves_other_known_fail_and_pass(self):
        for state in ('FAIL', 'PASS'):
            with self.subTest(known_state=state):
                fixture = self.dashboard()
                fixture.report_data = self.report_with_state(fixture, state)
                self.add_second(fixture)
                before = fixture.all_bytes()
                with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no checker replay')):
                    projection = fixture.projection()
                self.assertEqual(self.states(projection), {'SUMMARY': state, 'SECOND': 'UNKNOWN'})
                self.assertTrue(projection['observation']['gaps'])
                self.assertEqual(projection['business']['completion']['total'], 2)
                self.assertEqual(projection['business']['completion']['completed'], int(state == 'PASS'))
                self.assertEqual(projection['business']['budget'], fixture.record_data['budget'])
                self.assertEqual(projection['business']['steps'][1]['state'], state)
                self.assertEqual(fixture.all_bytes(), before)

    def test_partial_item_retains_own_failure_while_other_result_updates(self):
        fixture = self.dashboard()
        fixture.report_data = self.report_with_state(fixture, 'FAIL')
        second = self.add_second(fixture)
        self.save_report(second, self.report_with_state(fixture, 'PASS'))
        failed_bytes = fixture.report.read_bytes()
        archive = fixture.root / 'archived-first-failure.json'
        archive.write_bytes(failed_bytes)
        fixture.make_config()
        before = fixture.all_bytes()
        with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no checker replay')):
            with fixture.host.observer_from_config(fixture.config, poll_seconds=.02, idle_seconds=0) as observer:
                self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'FAIL', 'SECOND': 'PASS'})
                fixture.report.write_text('{"status":', encoding='utf-8')
                second_failed = self.report_with_state(fixture, 'FAIL')
                self.save_report(second, second_failed)
                partial = self.wait(observer, 'data', lambda s:
                    self.states(s) == {'SUMMARY': 'FAIL', 'SECOND': 'FAIL'} and s['observation']['gaps'])
                self.assertEqual(partial['business']['completion']['total'], 2)
                self.assertEqual(partial['business']['completion']['completed'], 0)
                self.assertEqual(partial['business']['budget'], fixture.record_data['budget'])
                # Another reader receives this same cache, not the stale whole
                # scope where the second item had passed.
                self.assertEqual(fixture.request(observer)['business'], partial['business'])
                fixture.report.write_bytes(failed_bytes)
                self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'FAIL', 'SECOND': 'FAIL'}
                          and not s['observation']['gaps'])
                repaired = self.report_with_state(fixture, 'PASS')
                repaired.pop('failure_kind', None)
                self.save_report(fixture.report, repaired)
                final = self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'PASS', 'SECOND': 'FAIL'})
                self.assertEqual(final['business']['completion']['total'], 2)
                self.assertEqual(final['business']['completion']['completed'], 1)
        before[fixture.report.name] = fixture.report.read_bytes()
        before[second.name] = second.read_bytes()
        self.assertEqual(fixture.all_bytes(), before)
        self.assertEqual(archive.read_bytes(), failed_bytes)

    def test_missing_first_report_recovers_without_clearing_sibling_failure(self):
        fixture = self.dashboard()
        second = self.add_second(fixture)
        self.save_report(second, self.report_with_state(fixture, 'FAIL'))
        original = fixture.report.read_bytes()
        fixture.report.unlink()
        fixture.make_config()
        with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no checker replay')):
            with fixture.host.observer_from_config(fixture.config, poll_seconds=.02, idle_seconds=0) as observer:
                self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'UNKNOWN', 'SECOND': 'FAIL'})
                fixture.report.write_bytes(original)
                restored = self.wait(observer, 'data', lambda s:
                    self.states(s) == {'SUMMARY': 'PASS', 'SECOND': 'FAIL'} and not s['observation']['gaps'])
                self.assertEqual(restored['business']['completion']['completed'], 1)
                self.assertEqual(restored['business']['completion']['total'], 2)
                self.assertEqual(restored['business']['budget'], fixture.record_data['budget'])

    def test_unreadable_previous_pass_is_not_counted_as_current_pass(self):
        fixture = self.dashboard()
        second = self.add_second(fixture)
        self.save_report(second, self.report_with_state(fixture, 'FAIL'))
        fixture.make_config()
        with fixture.host.observer_from_config(fixture.config, poll_seconds=.02, idle_seconds=0) as observer:
            self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'PASS', 'SECOND': 'FAIL'})
            fixture.report.write_text('{"checks":', encoding='utf-8')
            unavailable = self.wait(observer, 'data', lambda s:
                self.states(s) == {'SUMMARY': 'UNKNOWN', 'SECOND': 'FAIL'} and s['observation']['gaps'])
            self.assertEqual(unavailable['business']['completion']['completed'], 0)
            self.assertEqual(unavailable['business']['completion']['total'], 2)

    def test_native_data_unread_bindings_preserve_error_not_invalidated(self):
        fixture = self.fixture(data_fixture.CapabilityDataTests)
        # The first expectation read fails. Input/config/actual exist but the
        # native checker has not read them, so their bindings must remain null.
        fixture.output.write_text('{"engineering":"unread"}', encoding='utf-8')
        fixture.expected.write_text('broken independent expectation', encoding='utf-8')
        checked = fixture.run_check()
        self.assertEqual(checked.returncode, 1, checked.stderr)
        report = json.loads(fixture.report.read_text())
        self.assertEqual(report['checks'], [{'id': 'data-summary', 'status': 'ERROR'}])
        self.assertTrue(all(report['observation_binding']['files'][key] is None
                            for key in ('input', 'config', 'actual')))
        paths = {'input': fixture.source, 'config': fixture.config_path,
                 'actual': fixture.output, 'expected': fixture.expected}
        record, selection = self.native_record(fixture.root, 'data-summary', fixture.report, paths, 'data-summary')
        before = {path: path.read_bytes() for path in fixture.root.rglob('*') if path.is_file()}
        with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no checker replay')):
            for _ in range(2):
                projection = TARGET.read_target_projection(record, selection)
                self.assertEqual(self.states(projection), {'NATIVE': 'ERROR'})
                self.assertTrue(projection['observation']['gaps'])
                self.assertEqual(projection['business']['completion']['completed'], 0)
                self.assertEqual(projection['business']['budget']['attempts_consumed'], 1)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_native_doc_missing_product_input_preserves_assertion(self):
        fixture = self.fixture(doc_fixture.CapabilityDocTests)
        fixture.notes.unlink()
        checked, report = fixture.run_check()
        self.assertEqual(checked.returncode, 1, checked.stderr)
        self.assertEqual(report['failure_kind'], 'ASSERTION')
        self.assertEqual(report['checks'], [{'id': 'document-export', 'status': 'FAIL'}])
        self.assertFalse(report.get('input_bindings', {}).get('notes_sha256'))
        paths = {'tool': fixture.tool, 'config': fixture.config, 'notes': fixture.notes,
                 'sources': fixture.sources, 'expected': fixture.expected}
        record, selection = self.native_record(fixture.root, 'doc-export', fixture.report, paths, 'document-export')
        before = {path: path.read_bytes() for path in fixture.root.rglob('*') if path.is_file()}
        with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no CLI replay')):
            projection = TARGET.read_target_projection(record, selection)
        self.assertEqual(self.states(projection), {'NATIVE': 'FAIL'})
        self.assertTrue(projection['observation']['gaps'])
        self.assertEqual(projection['business']['steps'][0]['state'], 'FAIL')
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse(fixture.notes.exists())
        self.assertEqual(list(fixture.scratch.iterdir()), [])

    def test_changed_observed_hash_still_invalidates_error_report(self):
        fixture = self.dashboard()
        fixture.report_data = self.report_with_state(fixture, 'ERROR')
        bindings = fixture.report_data['observation_binding']['files']
        for key in ('input', 'config', 'actual'):
            bindings[key] = None
        fixture.save()
        report_bytes = fixture.report.read_bytes()
        self.assertEqual(self.states(fixture.projection()), {'SUMMARY': 'ERROR'})
        fixture.paths['expected'].write_bytes(b'changed after observed error')
        self.assertEqual(self.states(fixture.projection()), {'SUMMARY': 'INVALIDATED'})
        self.assertEqual(fixture.report.read_bytes(), report_bytes)

    def test_partial_pass_never_counts_and_does_not_hide_complete_sibling(self):
        variants = []
        fixture = self.dashboard()
        null = deepcopy(fixture.report_data)
        null['observation_binding']['files']['input'] = None
        variants.append(null)
        absent = deepcopy(fixture.report_data)
        absent['observation_binding']['files'].pop('actual')
        variants.append(absent)
        no_binding = deepcopy(fixture.report_data)
        no_binding.pop('observation_binding')
        variants.append(no_binding)
        wrong_check = deepcopy(fixture.report_data)
        wrong_check['checks'][0]['id'] = 'other-check'
        variants.append(wrong_check)
        second = self.add_second(fixture)
        self.save_report(second, self.report_with_state(fixture, 'PASS'))
        for report in variants:
            with self.subTest(report=report):
                self.save_report(fixture.report, report)
                projection = fixture.projection()
                self.assertEqual(self.states(projection), {'SUMMARY': 'UNKNOWN', 'SECOND': 'PASS'})
                self.assertTrue(projection['observation']['gaps'])
                self.assertEqual(projection['business']['completion']['completed'], 1)
                self.assertEqual(projection['business']['completion']['total'], 2)

    def test_wrong_required_check_does_not_claim_an_unrelated_failure(self):
        fixture = self.dashboard()
        fixture.report_data = self.report_with_state(fixture, 'FAIL')
        fixture.report_data['checks'][0]['id'] = 'unrelated-check'
        second = self.add_second(fixture)
        self.save_report(second, self.report_with_state(fixture, 'PASS'))
        # Make the complete second item explicitly select its own report ID.
        fixture.record_data['items'][1]['check_ids'] = ['unrelated-check']
        fixture.save()
        projection = fixture.projection()
        self.assertEqual(self.states(projection), {'SUMMARY': 'UNKNOWN', 'SECOND': 'PASS'})
        self.assertTrue(projection['observation']['gaps'])

    def test_invalid_scope_identity_is_not_downgraded_to_an_item_gap(self):
        fixture = self.dashboard()
        self.add_second(fixture)
        for selection in (dashboard_fixture.identity(version='other-version'),
                          dashboard_fixture.identity(run='other-run')):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                TARGET.read_target_projection(fixture.record, selection)

    def test_changed_scope_or_item_binding_does_not_carry_stale_failure(self):
        for change in ('scope', 'file-binding'):
            with self.subTest(change=change):
                fixture = self.dashboard()
                fixture.report_data = self.report_with_state(fixture, 'FAIL')
                fixture.save()
                fixture.make_config()
                with fixture.host.observer_from_config(fixture.config, poll_seconds=.02, idle_seconds=0) as observer:
                    self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'FAIL'})
                    fixture.report.write_text('{"checks":', encoding='utf-8')
                    self.wait(observer, 'data', lambda s:
                        self.states(s) == {'SUMMARY': 'FAIL'} and s['observation']['gaps'])
                    if change == 'scope':
                        fixture.record_data['scope_ref'] = 'new-scope'
                    else:
                        replacement = fixture.root / 'new-actual.dat'
                        replacement.write_bytes(fixture.paths['actual'].read_bytes())
                        fixture.record_data['items'][0]['files']['actual'] = {'path': replacement.name}
                    fixture.record.write_text(json.dumps(fixture.record_data), encoding='utf-8')
                    changed = self.wait(observer, 'data', lambda s:
                        self.states(s) == {'SUMMARY': 'UNKNOWN'} and s['observation']['gaps'])
                    self.assertEqual(changed['business']['completion']['completed'], 0)
                    self.assertEqual(changed['business']['budget'], fixture.record_data['budget'])

    def test_per_item_failure_cache_never_crosses_run_selection(self):
        fixture = self.dashboard()
        fixture.report_data = self.report_with_state(fixture, 'FAIL')
        fixture.save()
        fixture.make_config()
        second_record = fixture.root / 'other-run.json'
        second_report = fixture.root / 'other-run-report.json'
        second = deepcopy(fixture.record_data)
        second['selection'] = dashboard_fixture.identity(run='other-run')
        second['items'][0]['report'] = second_report.name
        second['budget'] = {'attempts_consumed': 5, 'attempts_remaining': 4}
        second_record.write_text(json.dumps(second), encoding='utf-8')
        self.save_report(second_report, self.report_with_state(fixture, 'PASS'))
        fixture.config_data['runs'].append({'id': 'second', 'selection': second['selection'],
                                           'record': second_record.name})
        fixture.config.write_text(json.dumps(fixture.config_data), encoding='utf-8')
        with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no checker replay')):
            with fixture.host.observer_from_config(fixture.config, poll_seconds=.02, idle_seconds=0) as observer:
                self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'FAIL'})
                self.wait(observer, 'second', lambda s: self.states(s) == {'SUMMARY': 'PASS'})
                fixture.report.write_text('{"checks":', encoding='utf-8')
                second_report.write_text('{"checks":', encoding='utf-8')
                first = self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'FAIL'}
                                  and s['observation']['gaps'])
                other = self.wait(observer, 'second', lambda s: self.states(s) == {'SUMMARY': 'UNKNOWN'}
                                  and s['observation']['gaps'])
                self.assertEqual(first['selection'], fixture.selection)
                self.assertEqual(other['selection'], second['selection'])
                self.assertEqual(first['business']['budget'], fixture.record_data['budget'])
                self.assertEqual(other['business']['budget'], second['budget'])
                self.assertEqual(other['business']['completion']['completed'], 0)


    def test_rejected_projection_cannot_clear_committed_failure_cache(self):
        fixture = self.dashboard()
        fixture.report_data = self.report_with_state(fixture, 'FAIL')
        fixture.save()
        valid_mapping = fixture.record.read_bytes()
        fixture.make_config()
        with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no checker replay')):
            with fixture.host.observer_from_config(fixture.config, poll_seconds=.02, idle_seconds=0) as observer:
                self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'FAIL'})
                # Make the mapping invalid before supplying PASS, so that no
                # valid collection can legitimately replace the cached FAIL.
                fixture.record_data['steps'].append(deepcopy(fixture.record_data['steps'][0]))
                fixture.record.write_text(json.dumps(fixture.record_data), encoding='utf-8')
                rejected = self.wait(observer, 'data', lambda s:
                    'SOURCE_UNAVAILABLE' in s['observation']['gaps'])
                sequence = rejected['transport']['sequence']
                self.save_report(fixture.report, self.report_with_state(fixture, 'PASS'))
                # Two subsequent collections ensure the complete PASS has
                # been read after the write, then rejected by shared validation.
                rejected = self.wait(observer, 'data', lambda s:
                    s['transport']['sequence'] >= sequence + 2
                    and 'SOURCE_UNAVAILABLE' in s['observation']['gaps'])
                self.assertEqual(self.states(rejected), {'SUMMARY': 'FAIL'})
                fixture.report.write_text('{"checks":', encoding='utf-8')
                fixture.record.write_bytes(valid_mapping)
                recovered_mapping = self.wait(observer, 'data', lambda s:
                    'SOURCE_UNAVAILABLE' not in s['observation']['gaps']
                    and bool(s['observation']['gaps']))
                self.assertEqual(self.states(recovered_mapping), {'SUMMARY': 'FAIL'})
                self.assertEqual(recovered_mapping['business']['completion']['completed'], 0)
                self.assertEqual(recovered_mapping['business']['budget'], fixture.record_data['budget'])

    def test_retained_failure_keeps_original_evidence_reference_during_report_handoff(self):
        fixture = self.dashboard()
        fixture.report_data = self.report_with_state(fixture, 'FAIL')
        fixture.record_data['items'][0]['evidence_ref'] = 'old'
        fixture.save()
        old_report = fixture.report.read_bytes()
        fixture.make_config()
        with self.no_dispatch(), patch('subprocess.run', side_effect=AssertionError('no checker replay')):
            with fixture.host.observer_from_config(fixture.config, poll_seconds=.02, idle_seconds=0) as observer:
                self.wait(observer, 'data', lambda s: self.states(s) == {'SUMMARY': 'FAIL'})
                new_report = fixture.root / 'new-report.json'
                new_report.write_text('{"checks":', encoding='utf-8')
                fixture.record_data['items'][0].update(report=new_report.name, evidence_ref='new')
                fixture.record.write_text(json.dumps(fixture.record_data), encoding='utf-8')
                handed_off = self.wait(observer, 'data', lambda s:
                    self.states(s) == {'SUMMARY': 'FAIL'} and bool(s['observation']['gaps']))
                self.assertEqual(handed_off['business']['items'][0]['evidence_refs'], ['old'])
                self.assertEqual(fixture.report.read_bytes(), old_report)
                # The new reference becomes current only with an interpretable
                # report at the explicitly selected new location.
                self.save_report(new_report, self.report_with_state(fixture, 'PASS'))
                restored = self.wait(observer, 'data', lambda s:
                    self.states(s) == {'SUMMARY': 'PASS'} and not s['observation']['gaps'])
                self.assertEqual(restored['business']['items'][0]['evidence_refs'], ['new'])
                self.assertEqual(restored['business']['completion']['completed'], 1)
                self.assertEqual(restored['business']['budget'], fixture.record_data['budget'])
                self.assertEqual(fixture.report.read_bytes(), old_report)


if __name__ == '__main__':
    unittest.main()
