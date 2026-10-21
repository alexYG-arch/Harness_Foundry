"""WP08 isolated observer fixtures; these are not target business/H01-H09 acceptance.

The report bytes below model existing checker receipts. Tests never ask the
observer to run those checkers, regenerate outputs, or change business records.
"""

from copy import deepcopy
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'examples/capability-adapters/packages/local-dashboard/1'
spec = importlib.util.spec_from_file_location('wp08_target_dashboard', PACKAGE / 'target.py')
TARGET = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TARGET)


def identity(version='1', run='run-1'):
    return dict(kind='harness_run', project_id='isolated-target',
                project_version=version, run_id=run)


def sha(value):
    return hashlib.sha256(value).hexdigest()


class TargetDashboardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='wp08-target-dashboard-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.selection = identity()
        self.record = self.root / 'run-record.json'
        self.report = self.root / 'check-report.json'
        self.paths = {}
        for name, body in {'input': b'category,value\na,2\n', 'config': b'{"units":"count"}',
                           'actual': b'{"summary":"fixture"}', 'expected': b'{"summary":"fixture"}'}.items():
            path = self.root / (name + '.dat')
            path.write_bytes(body)
            self.paths[name] = path
        self.report_data = {
            'schema_version': '1.0', 'case_id': 'standalone', 'command_id': 'standalone',
            'status': 'CHECKS_PASS', 'checks': [{'id': 'data-summary', 'status': 'PASS'}], 'errors': [],
            'observation_binding': {'format': 'data-summary', 'files': {
                name: sha(path.read_bytes()) for name, path in self.paths.items()}},
        }
        self.record_data = {
            'selection': self.selection, 'title': '隔离 DATA 运行记录', 'scope_ref': 'scope-data-1',
            'scope_complete': True,
            'items': [{'item_id': 'SUMMARY', 'label': '汇总结果', 'format': 'data-summary',
                       'report': self.report.name,
                       'files': {name: {'path': path.name} for name, path in self.paths.items()},
                       'check_ids': ['data-summary'], 'evidence_ref': 'data-check-1'}],
            'steps': [{'step_id': 'EXPORT', 'label': '生成汇总', 'item_id': 'SUMMARY',
                       'phase': 'output', 'depends_on': []},
                      {'step_id': 'CHECK', 'label': '独立检查', 'item_id': 'SUMMARY',
                       'phase': 'check', 'depends_on': ['EXPORT']}],
            'budget': {'attempts_consumed': 2, 'attempts_remaining': 7},
        }
        self.save()

    def save(self):
        self.record.write_text(json.dumps(self.record_data), encoding='utf-8')
        self.report.write_text(json.dumps(self.report_data), encoding='utf-8')

    def projection(self):
        return TARGET.read_target_projection(self.record, self.selection)

    def assert_current_not_pass(self):
        try:
            projection = self.projection()
        except ValueError:
            # An incomplete receipt is unavailable; Observer keeps the last
            # valid snapshot instead of overwriting it with a fresh PASS.
            return
        self.assertNotEqual(projection['business']['items'][0]['state'], 'PASS')
        completion = projection['business'].get('completion')
        if completion is not None:
            self.assertEqual(completion['completed'], 0)

    def all_bytes(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def make_config(self):
        self.package = self.root / 'delivered-dashboard'
        shutil.copytree(PACKAGE, self.package)
        descriptor = json.loads((self.package / 'capability.json').read_text())
        names = set(descriptor.get('materials', [])) | set(descriptor.get('runtime_files', []))
        names.update(tool['path'] for tool in descriptor.get('tools', []))
        self.config = self.root / 'observer.json'
        self.config_data = {
            'component': {'name': descriptor['name'], 'version': descriptor['version'],
                          'files': [{'path': name,
                                     'sha256': sha((self.package / name).read_bytes())}
                                    for name in sorted(names)]},
            'runs': [{'id': 'data', 'selection': self.selection, 'record': self.record.name}],
        }
        self.config.write_text(json.dumps(self.config_data), encoding='utf-8')
        spec = importlib.util.spec_from_file_location('wp08_detached_target_dashboard', self.package / 'target.py')
        self.host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.host)
        return self.config

    def request(self, service, route='api/snapshot?run=data'):
        parsed = urlsplit(service.url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            conn.request('GET', parsed.path + route)
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            return json.loads(response.read())
        finally:
            conn.close()

    def test_bound_complete_data_report_maps_original_steps_and_budget(self):
        before = self.all_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('observer must not dispatch')), \
                patch('subprocess.run', side_effect=AssertionError('observer must not run checker')):
            projection = self.projection()
        self.assertEqual(projection['selection'], self.selection)
        business = projection['business']
        self.assertEqual(business['items'][0]['state'], 'PASS')
        self.assertEqual(business['items'][0]['evidence_refs'], ['data-check-1'])
        self.assertEqual([row['state'] for row in business['steps']], ['PASS', 'PASS'])
        self.assertEqual(business['steps'][1]['depends_on'], ['EXPORT'])
        self.assertEqual(business['completion']['completed'], 1)
        self.assertEqual(business['completion']['total'], 1)
        self.assertEqual(business['budget'], self.record_data['budget'])
        self.assertEqual(before, self.all_bytes())

    def test_stale_inputs_outputs_and_private_expectation_do_not_display_old_pass(self):
        for name in self.paths:
            with self.subTest(file=name):
                path = self.paths[name]
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                self.assert_current_not_pass()
                path.write_bytes(original)
        self.assertEqual(self.projection()['business']['items'][0]['state'], 'PASS')

    def test_hash_only_private_expected_remains_supported_without_exposing_it(self):
        expected_hash = sha(self.paths['expected'].read_bytes())
        self.record_data['items'][0]['files']['expected'] = {'sha256': expected_hash}
        self.paths['expected'].unlink()
        self.save()
        before = self.all_bytes()
        projection = self.projection()
        self.assertEqual(projection['business']['items'][0]['state'], 'PASS')
        self.assertNotIn(expected_hash, json.dumps(projection))
        self.assertEqual(before, self.all_bytes())

    def test_old_missing_binding_and_incomplete_pass_receipts_remain_unverified(self):
        variants = []
        missing = deepcopy(self.report_data); missing.pop('observation_binding'); variants.append(missing)
        no_actual = deepcopy(self.report_data); no_actual['observation_binding']['files'].pop('actual'); variants.append(no_actual)
        unknown_input = deepcopy(self.report_data); unknown_input['observation_binding']['files']['input'] = None; variants.append(unknown_input)
        no_checks = deepcopy(self.report_data); no_checks['checks'] = []; variants.append(no_checks)
        wrong_check = deepcopy(self.report_data); wrong_check['checks'][0]['id'] = 'different-check'; variants.append(wrong_check)
        duplicated = deepcopy(self.report_data); duplicated['checks'] *= 2; variants.append(duplicated)
        inconsistent = deepcopy(self.report_data); inconsistent['checks'][0]['status'] = 'FAIL'; variants.append(inconsistent)
        for report in variants:
            with self.subTest(report=report):
                self.report.write_text(json.dumps(report))
                self.assert_current_not_pass()

    def test_first_read_of_old_unbound_report_remains_unknown(self):
        self.report_data.pop('observation_binding')
        self.save()
        self.make_config()
        before = self.all_bytes()
        with self.host.observer_from_config(self.config, poll_seconds=60, idle_seconds=0) as observer:
            snapshot = self.request(observer)
            self.assertEqual(snapshot['business']['completion']['completed'], 0)
            self.assertEqual(snapshot['business']['completion']['total'], 1)
            self.assertTrue(snapshot['observation']['gaps'])
            self.assertEqual(snapshot['business']['items'][0]['state'], 'UNKNOWN')
        self.assertEqual(self.all_bytes(), before)

    def test_declared_required_check_missing_does_not_accept_partial_pass(self):
        self.record_data['items'][0]['check_ids'].append('independent-second-check')
        self.save()
        self.assert_current_not_pass()

    def test_failed_check_and_extra_failure_remain_visible_without_raw_diagnostics(self):
        self.report_data.update(status='CHECKS_FAILED', failure_kind='ASSERTION',
                                diagnostic='/private/PRIVATE-TOKEN problem', errors=[])
        self.report_data['checks'][0]['status'] = 'FAIL'
        self.save()
        projection = self.projection()
        self.assertEqual(projection['business']['items'][0]['state'], 'FAIL')
        self.assertEqual(projection['business']['steps'][1]['state'], 'FAIL')
        self.assertNotIn('PRIVATE-TOKEN', json.dumps(projection))
        self.assertNotIn(str(self.root), json.dumps(projection))
        # An additional supplied finding cannot be erased by selecting just the
        # passing required check for display.
        self.report_data['checks'] = [{'id': 'data-summary', 'status': 'PASS'},
                                      {'id': 'extra-finding', 'status': 'FAIL'}]
        self.save()
        self.assertEqual(self.projection()['business']['items'][0]['state'], 'FAIL')

    def test_unknown_scope_does_not_invent_completion_denominator(self):
        self.record_data['scope_complete'] = False
        self.save()
        projection = self.projection()
        self.assertIsNone(projection['business']['completion'])
        self.assertEqual(projection['business']['items'][0]['state'], 'PASS')

    def test_reread_and_retry_do_not_inflate_items_or_budget(self):
        first = self.projection()
        for _ in range(3):
            self.assertEqual(self.projection(), first)
        self.report_data.update(status='CHECKS_FAILED', failure_kind='ASSERTION')
        self.report_data['checks'][0]['status'] = 'FAIL'
        self.save()
        failed = self.projection()
        self.assertNotEqual(first['business']['source_revision'], failed['business']['source_revision'])
        self.record_data['budget'] = {'attempts_consumed': 3, 'attempts_remaining': 6}
        self.report_data.update(status='CHECKS_PASS')
        self.report_data.pop('failure_kind')
        self.report_data['checks'][0]['status'] = 'PASS'
        self.save()
        repaired = self.projection()
        self.assertEqual(repaired['business']['completion']['total'], 1)
        self.assertEqual(len(repaired['business']['items']), 1)
        self.assertEqual(repaired['business']['budget'], self.record_data['budget'])

    def test_run_or_version_mismatch_never_falls_back_to_available_report(self):
        for selection in (identity(run='another-run'), identity(version='another-version')):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                TARGET.read_target_projection(self.record, selection)

    def test_duplicate_item_and_invalid_step_references_are_rejected(self):
        original = deepcopy(self.record_data)
        variants = []
        duplicate = deepcopy(original); duplicate['items'] *= 2; variants.append(duplicate)
        unknown = deepcopy(original); unknown['steps'][0]['item_id'] = 'MISSING'; variants.append(unknown)
        duplicate_step = deepcopy(original); duplicate_step['steps'].append(duplicate_step['steps'][0]); variants.append(duplicate_step)
        for record in variants:
            with self.subTest(record=record):
                self.record_data = record; self.save()
                with self.assertRaises((ValueError, KeyError)):
                    projection = self.projection()
                    TARGET._load_dashboard().normalize_projection(projection, self.selection)

    def wait_snapshot(self, observer, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = self.request(observer)
            if predicate(snapshot):
                return snapshot
            time.sleep(.01)
        self.fail('expected observer snapshot was not collected')

    def test_missing_and_partial_first_report_stays_unknown_without_reexecution(self):
        self.make_config()
        before = self.all_bytes()
        before_report = self.report.read_bytes()
        self.report.unlink()
        with patch('subprocess.Popen', side_effect=AssertionError('observer dispatch')), \
                patch('subprocess.run', side_effect=AssertionError('must not regenerate report')):
            self.assertEqual(self.projection()['business']['items'][0]['state'], 'UNKNOWN')
            with self.host.observer_from_config(self.config, poll_seconds=.02, idle_seconds=0) as observer:
                missing = self.request(observer)
                self.assertEqual(missing['business']['completion']['completed'], 0)
                self.assertTrue(missing['observation']['gaps'])
                self.report.write_text('{"status":')
                self.assertEqual(self.projection()['business']['items'][0]['state'], 'UNKNOWN')
                partial = self.request(observer)
                self.assertEqual(partial['business']['completion']['completed'], 0)
                self.assertTrue(partial['observation']['gaps'])
                self.report.write_bytes(before_report)
                restored = self.wait_snapshot(observer, lambda snapshot: not snapshot['observation']['gaps'])
                self.assertEqual(restored['business']['items'][0]['state'], 'PASS')
        self.assertEqual(self.all_bytes(), before)

    def test_report_read_gap_preserves_prior_failure_until_bound_pass_arrives(self):
        self.report_data.update(status='CHECKS_FAILED', failure_kind='ASSERTION')
        self.report_data['checks'][0]['status'] = 'FAIL'
        self.save()
        failed_bytes = self.report.read_bytes()
        (self.root / 'archived-failed-report.json').write_bytes(failed_bytes)
        self.make_config()
        before = self.all_bytes()
        passed = deepcopy(self.report_data)
        passed.update(status='CHECKS_PASS')
        passed.pop('failure_kind')
        passed['checks'][0]['status'] = 'PASS'
        passed_bytes = json.dumps(passed).encode()
        with patch('subprocess.Popen', side_effect=AssertionError('observer dispatch')), \
                patch('subprocess.run', side_effect=AssertionError('observer checker replay')):
            with self.host.observer_from_config(self.config, poll_seconds=.02, idle_seconds=0) as observer:
                original = self.request(observer)
                self.assertEqual(original['business']['items'][0]['state'], 'FAIL')
                for corruption in ('absent', 'partial', 'empty-object', 'missing-checks', 'missing-binding'):
                    with self.subTest(corruption=corruption):
                        if corruption == 'absent':
                            self.report.unlink()
                        elif corruption == 'partial':
                            self.report.write_text('{"status":')
                        else:
                            incomplete = json.loads(failed_bytes)
                            if corruption == 'empty-object':
                                incomplete = {}
                            elif corruption == 'missing-checks':
                                incomplete.pop('checks')
                            else:
                                incomplete.pop('observation_binding')
                            self.report.write_text(json.dumps(incomplete))
                        unavailable = self.wait_snapshot(observer, lambda snapshot:
                            bool(snapshot['observation']['gaps']))
                        self.assertEqual(unavailable['business']['completion'], original['business']['completion'])
                        self.assertEqual(unavailable['business']['budget'], original['business']['budget'])
                        self.assertEqual(unavailable['business']['items'][0]['state'], 'FAIL')
                        # Another HTTP connection reads the same retained state.
                        self.assertEqual(self.request(observer)['business']['items'], original['business']['items'])
                        self.report.write_bytes(failed_bytes)
                        restored = self.wait_snapshot(observer, lambda snapshot: not snapshot['observation']['gaps'])
                        self.assertEqual(restored['business']['items'][0]['state'], 'FAIL')
                self.report.write_bytes(passed_bytes)
                repaired = self.wait_snapshot(observer, lambda snapshot:
                    snapshot['business']['items'][0]['state'] == 'PASS')
                self.assertEqual(repaired['business']['budget'], self.record_data['budget'])
                self.assertEqual(repaired['business']['completion']['total'], 1)
        # Only the fixture's explicitly replaced current report changes. The
        # archived failed evidence, outputs, mapping and component remain intact.
        before[self.report.name] = passed_bytes
        self.assertEqual(self.all_bytes(), before)

    def test_empty_scope_and_absent_budget_are_not_inferred(self):
        self.record_data.update(items=[], steps=[])
        self.record_data.pop('budget')
        self.save()
        projection = self.projection()
        self.assertIsNone(projection['business']['completion'])
        self.assertNotIn('budget', projection['business'])
        self.assertEqual(projection['business']['items'], [])

    def test_same_run_different_version_sources_do_not_mix(self):
        self.make_config()
        second_record = self.root / 'second-version.json'
        second = deepcopy(self.record_data)
        second['selection'] = identity(version='2')
        second['budget'] = {'attempts_consumed': 5, 'attempts_remaining': 2}
        second_record.write_text(json.dumps(second))
        self.config_data['runs'].append({'id': 'second', 'selection': second['selection'],
                                         'record': second_record.name})
        self.config.write_text(json.dumps(self.config_data))
        before = self.all_bytes()
        with self.host.observer_from_config(self.config, poll_seconds=60, idle_seconds=0) as observer:
            first = self.request(observer)
            second_snapshot = self.request(observer, 'api/snapshot?run=second')
            self.assertEqual(first['selection']['project_version'], '1')
            self.assertEqual(first['business']['budget']['attempts_consumed'], 2)
            self.assertEqual(second_snapshot['selection']['project_version'], '2')
            self.assertEqual(second_snapshot['business']['budget']['attempts_consumed'], 5)
        self.assertEqual(before, self.all_bytes())

    def test_unreadable_scope_keeps_last_failed_snapshot_and_reconnect_does_not_clear_failure(self):
        self.report_data.update(status='CHECKS_FAILED', failure_kind='ASSERTION')
        self.report_data['checks'][0]['status'] = 'FAIL'
        self.save()
        self.make_config()
        original_record = self.record.read_bytes()
        with self.host.observer_from_config(self.config, poll_seconds=.02, idle_seconds=0) as observer:
            self.assertEqual(self.request(observer)['business']['items'][0]['state'], 'FAIL')
            self.record.write_text('{partial')
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                snapshot = self.request(observer)
                if 'SOURCE_UNAVAILABLE' in snapshot['observation']['gaps']:
                    break
                time.sleep(.01)
            else:
                self.fail('missing source-unavailable indication')
            self.assertEqual(snapshot['business']['items'][0]['state'], 'FAIL')
            self.record.write_bytes(original_record)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                snapshot = self.request(observer)
                if not snapshot['observation']['gaps']:
                    break
                time.sleep(.01)
            else:
                self.fail('restored original scope was not observed')
            self.assertEqual(snapshot['business']['items'][0]['state'], 'FAIL')
            self.assertEqual(snapshot['business']['budget'], self.record_data['budget'])

    def test_bound_doc_export_needs_actual_cli_receipt_and_keeps_failed_check(self):
        self.paths = {}
        for name in ('tool', 'config', 'notes', 'sources', 'expected'):
            path = self.root / (name + '.doc-input')
            path.write_bytes((name + ' fixture').encode())
            self.paths[name] = path
        actual = '# Report\n\n## Facts\nOne fact.\n'
        self.report_data = {
            'status': 'CHECKS_PASS', 'checks': [{'id': 'document-export', 'status': 'PASS'}], 'errors': [],
            'input_bindings': {name + '_sha256': sha(path.read_bytes())
                               for name, path in self.paths.items() if name != 'expected'},
            'expected_sha256': sha(self.paths['expected'].read_bytes()),
            'actual_export': actual, 'actual_sha256': sha(actual.encode()),
            'execution': {'returncode': 0, 'invocation_attempts': 1},
        }
        item = self.record_data['items'][0]
        item.update(format='doc-export', check_ids=['document-export'],
                    files={name: {'path': path.name} for name, path in self.paths.items()})
        self.save()
        self.assertEqual(self.projection()['business']['items'][0]['state'], 'PASS')
        original = deepcopy(self.report_data)
        for field, value in (('actual_sha256', '0' * 64), ('execution', {}),
                             ('execution', {'returncode': 1, 'invocation_attempts': 1}),
                             ('execution', {'returncode': 0, 'invocation_attempts': 0})):
            with self.subTest(field=field, value=value):
                self.report_data = deepcopy(original); self.report_data[field] = value; self.save()
                self.assert_current_not_pass()
        self.report_data = deepcopy(original)
        self.report_data.update(status='CHECKS_FAILED', failure_kind='ASSERTION')
        self.report_data['checks'][0]['status'] = 'FAIL'
        self.save()
        self.assertEqual(self.projection()['business']['items'][0]['state'], 'FAIL')

    def make_host_receipt(self):
        task_root = self.root / 'host-task'
        snapshot_root = self.root / 'host-snapshot'
        outputs_root = self.root / 'host-outputs'
        task_root.mkdir(); outputs_root.mkdir(); snapshot_root.mkdir()
        task = {'task_id': 'prd-fixture', 'workflow': 'workflow.md',
                'inputs': {'brief': 'brief.json'}, 'outputs': ['review.md'],
                'host_tools': ['isolated fixture supplied observation']}
        snapshot = {'task_id': 'prd-fixture', 'reviewer': 'independent-fixture-reviewer',
                    'input_files': {'brief': 'inputs/0'},
                    'observations': [{'id': 'requirement-coverage', 'result': 'PASS',
                                      'reason': 'fixture observation matches the stated scope',
                                      'evidence_refs': ['evidence/readback.txt']}]}
        bodies = {
            'task': (task_root / 'task.json', json.dumps(task).encode()),
            'workflow': (task_root / 'workflow.md', b'Review the supplied brief and output.'),
            'input:brief': (task_root / 'brief.json', b'{"requirement":"traceable output"}'),
            'output:review.md': (outputs_root / 'review.md', b'# Review\nTraceable output.\n'),
            'snapshot': (snapshot_root / 'snapshot.json', json.dumps(snapshot).encode()),
            'expectation': (self.root / 'host-expectation.json', json.dumps({
                'task_id': 'prd-fixture', 'required_observations': ['requirement-coverage']}).encode()),
            'snapshot:evidence/readback.txt': (snapshot_root / 'evidence/readback.txt',
                                               b'Isolated observation evidence, not a real business review.'),
        }
        for snapshot_name, source_key in [('task/task.json', 'task'), ('task/workflow', 'workflow'),
                                           ('inputs/0', 'input:brief'), ('outputs/review.md', 'output:review.md')]:
            bodies['snapshot:' + snapshot_name] = (snapshot_root / snapshot_name, bodies[source_key][1])
        files = {}
        for name, (path, body) in bodies.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            files[name] = path
        item = self.record_data['items'][0]
        item.update(format='host-review', check_ids=['host-review'],
                    files={name: {'path': str(path.relative_to(self.root))} for name, path in files.items()})
        self.report_data = {
            'status': 'CHECKS_PASS', 'checks': [{'id': 'host-review', 'status': 'PASS'}], 'errors': [],
            'scope': 'Supplied independent host observations only',
            'observation_binding': {'format': 'host-review', 'files': {
                name: sha(path.read_bytes()) for name, path in files.items()}},
        }
        self.save()
        return files

    def test_host_review_uses_complete_bound_task_snapshot_and_output_files(self):
        files = self.make_host_receipt()
        self.assertEqual(self.projection()['business']['items'][0]['state'], 'PASS')
        files['output:review.md'].write_text('new output is not the reviewed bytes')
        self.assert_current_not_pass()

    def test_host_review_cannot_omit_output_from_both_mapping_and_report_binding(self):
        self.make_host_receipt()
        self.record_data['items'][0]['files'].pop('output:review.md')
        self.report_data['observation_binding']['files'].pop('output:review.md')
        self.save()
        self.assert_current_not_pass()
        self.make_config()
        with self.host.observer_from_config(self.config, poll_seconds=60, idle_seconds=0) as observer:
            snapshot = self.request(observer)
            self.assertEqual(snapshot['business']['completion']['completed'], 0)
            self.assertEqual(snapshot['business']['items'][0]['state'], 'UNKNOWN')
            self.assertTrue(snapshot['observation']['gaps'])

    def test_detached_selected_component_serves_cached_views_without_dispatch_or_writes(self):
        self.make_config()
        before = self.all_bytes()
        original = self.host.read_target_projection
        with patch.object(self.host, 'read_target_projection', wraps=original) as reader, \
                patch('subprocess.Popen', side_effect=AssertionError('observer dispatch')):
            observer = self.host.observer_from_config(self.config, poll_seconds=60, idle_seconds=0)
            self.addCleanup(observer.stop)
            observer.start()
            self.assertEqual(reader.call_count, 1)
            for _ in range(3):
                projection = self.request(observer)
                self.assertEqual(projection['selection'], self.selection)
                self.assertEqual(projection['business']['completion']['completed'], 1)
            self.assertEqual(reader.call_count, 1)
            observer.stop()
        self.assertEqual(before, self.all_bytes())

    def test_changed_selected_component_or_incomplete_file_binding_is_rejected(self):
        self.make_config()
        original = (self.package / 'web/app.js').read_bytes()
        (self.package / 'web/app.js').write_bytes(original + b'\n// changed after selection\n')
        with self.assertRaises(ValueError):
            self.host.observer_from_config(self.config)
        (self.package / 'web/app.js').write_bytes(original)
        self.config_data['component']['files'] = [row for row in self.config_data['component']['files']
                                                  if not row['path'].endswith('web/app.js')]
        self.config.write_text(json.dumps(self.config_data))
        with self.assertRaises(ValueError):
            self.host.observer_from_config(self.config)

    def test_detached_cli_restart_and_stop_do_not_replay_or_mutate_business(self):
        self.make_config()
        before = self.all_bytes()
        sessions = []
        for _ in range(2):
            process = subprocess.Popen([sys.executable, '-I', '-B', str(self.package / 'target.py'),
                '--config', str(self.config), '--poll-seconds', '60', '--idle-seconds', '0'],
                cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
            try:
                self.assertTrue(select.select([process.stdout], [], [], 8)[0], 'no startup output')
                startup = json.loads(process.stdout.readline())
                self.assertIn('url', startup)
                sessions.append(startup['session_id'])
                parsed = urlsplit(startup['url'])
                conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                try:
                    conn.request('GET', parsed.path + 'api/snapshot?run=data')
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())['business']['items'][0]['state'], 'PASS')
                finally:
                    conn.close()
                process.terminate()
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                with self.assertRaises(OSError):
                    socket.create_connection((parsed.hostname, parsed.port), timeout=.2)
            finally:
                if process.poll() is None:
                    process.kill(); process.communicate()
        self.assertNotEqual(*sessions)
        self.assertEqual(before, self.all_bytes())


if __name__ == '__main__':
    unittest.main()
