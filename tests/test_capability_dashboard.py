"""WP05 engineering fixtures, not real Foundry/target/PiP acceptance."""
from copy import deepcopy
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'examples/capability-adapters/packages/local-dashboard/1'
spec = importlib.util.spec_from_file_location('wp05_dashboard', PACKAGE / 'dashboard.py')
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def identity(project='example', version='1', run='run-1'):
    return dict(kind='harness_run', project_id=project, project_version=version, run_id=run)


def projection(selection=None):
    return {
        'selection': deepcopy(selection or identity()),
        'business': {'source_revision': 1, 'scope_ref': 'scope-1',
                     'title': '本轮工程夹具', 'current': '核对导出',
                     'items': [{'item_id': 'EXPORT', 'label': '导出', 'state': 'PENDING', 'evidence_refs': ['receipt-1']}],
                     'completion': None, 'pending': [], 'recent': [],
                     'budget': {'attempts_consumed': 2, 'attempts_remaining': 3}},
        'observation': {'activity': {'last_output_at': None}},
    }


class Source:
    def __init__(self, data=None):
        self.data = data or projection()
        self.calls = 0
        self.error = None
        self.lock = threading.Lock()

    def read(self):
        with self.lock:
            self.calls += 1
            if self.error:
                raise self.error
            return deepcopy(self.data)

    def set(self, data):
        with self.lock:
            self.data = deepcopy(data)


class DashboardTests(unittest.TestCase):
    def observer(self, sources=None, **options):
        self.source = Source()
        service = D.Observer(sources or {'one': {'selection': identity(), 'reader': self.source.read}},
                             **options)
        self.addCleanup(service.stop)
        service.start()
        return service

    def request(self, service, route, headers=None, method='GET'):
        url = urlsplit(service.url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
        conn.request(method, url.path + route, headers=headers or {})
        response = conn.getresponse()
        body = response.read()
        result = response.status, dict(response.getheaders()), body
        conn.close()
        return result

    def subscribe(self, service, run='one', headers=None):
        url = urlsplit(service.url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
        conn.request('GET', url.path + 'api/events?run=' + run, headers=headers or {})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.addCleanup(response.close)
        self.addCleanup(conn.close)
        return conn, response

    def event(self, response):
        data = []
        while True:
            line = response.readline()
            self.assertTrue(line, 'SSE ended before snapshot')
            line = line.decode().rstrip('\r\n')
            if line.startswith('data:'):
                data.append(line[5:].strip())
            elif not line and data:
                return json.loads('\n'.join(data))

    def eventually(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.01)
        self.fail('condition did not become true')

    def test_contract_retains_unknown_completion_and_original_budget(self):
        raw = projection()
        raw['env'] = {'TOKEN': 'SECRET'}
        raw['business']['raw_output'] = '/private/secret SECRET'
        raw['business']['budget']['credential'] = 'SECRET'
        normalized = D.normalize_projection(raw, identity())
        self.assertIsNone(normalized['business']['completion'])
        self.assertEqual(normalized['business']['budget'], {'attempts_consumed': 2, 'attempts_remaining': 3})
        self.assertNotIn('SECRET', json.dumps(normalized))
        self.assertEqual(raw['env']['TOKEN'], 'SECRET')

    def test_identity_mismatch_and_invalid_completion_rejected(self):
        raw = projection(identity('another'))
        with self.assertRaises(ValueError):
            D.normalize_projection(raw, identity())
        for completed, total in ((1, 0), (2, 1), (-1, 3), (math.nan, 3), (1, math.inf)):
            with self.subTest(completed=completed, total=total):
                raw = projection()
                raw['business']['completion'] = {'completed': completed, 'total': total, 'label': '成果项'}
                with self.assertRaises(ValueError):
                    D.normalize_projection(raw, identity())

    def test_duplicate_items_rejected_instead_of_double_counted(self):
        raw = projection()
        raw['business']['items'] *= 2
        with self.assertRaises(ValueError):
            D.normalize_projection(raw, identity())

    def test_steps_are_optional_allowlisted_and_do_not_replace_completion_or_budget(self):
        raw = projection()
        old = D.normalize_projection(raw, identity())
        self.assertNotIn('steps', old['business'])
        self.assertNotIn('current_step_id', old['business'])
        raw['business'].update(steps=[
            {'step_id': 'READ', 'label': '读取', 'state': 'ACCEPTED', 'detail': '已记录', 'depends_on': [],
             'raw_output': 'PRIVATE-STEP-OUTPUT'},
            {'step_id': 'EXPORT', 'label': '导出', 'state': 'UNKNOWN',
             'detail': '最近记录阶段：独立检查；尝试待结算', 'depends_on': ['READ']}],
            current_step_id='EXPORT')
        normalized = D.normalize_projection(raw, identity())
        self.assertEqual(normalized['business']['current_step_id'], 'EXPORT')
        self.assertEqual([row['step_id'] for row in normalized['business']['steps']], ['READ', 'EXPORT'])
        self.assertEqual(normalized['business']['steps'][1]['depends_on'], ['READ'])
        self.assertNotIn('PRIVATE-STEP-OUTPUT', json.dumps(normalized))
        self.assertEqual(normalized['business']['completion'], old['business']['completion'])
        self.assertEqual(normalized['business']['budget'], old['business']['budget'])
        normalized['business']['steps'][1]['depends_on'].clear()
        self.assertEqual(raw['business']['steps'][1]['depends_on'], ['READ'])

    def test_steps_reject_ambiguous_ids_or_unknown_references(self):
        valid = [{'step_id': 'READ', 'state': 'ACCEPTED', 'depends_on': []},
                 {'step_id': 'EXPORT', 'state': 'PENDING', 'depends_on': ['READ']}]
        variants = [None, {}, ['READ'], valid + [valid[0]],
                    [{**valid[0], 'step_id': ''}],
                    [valid[0], {**valid[1], 'depends_on': ['MISSING']}],
                    [valid[0], {**valid[1], 'depends_on': ['EXPORT']}],
                    [valid[0], {**valid[1], 'depends_on': ['READ', 'READ']}],
                    [valid[0], {**valid[1], 'depends_on': 'READ'}]]
        for steps in variants:
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                raw = projection(); raw['business']['steps'] = steps
                D.normalize_projection(raw, identity())
        for steps, current in ((valid, 'MISSING'), (valid, ''), ([], 'READ')):
            with self.subTest(current=current), self.assertRaises(ValueError):
                raw = projection(); raw['business'].update(steps=steps, current_step_id=current)
                D.normalize_projection(raw, identity())
        raw = projection(); raw['business']['current_step_id'] = 'READ'
        with self.assertRaises(ValueError):
            D.normalize_projection(raw, identity())

    def test_empty_steps_and_no_current_step_keep_legacy_unknown_completion(self):
        raw = projection(); raw['business'].update(steps=[], current_step_id=None)
        normalized = D.normalize_projection(raw, identity())
        self.assertEqual(normalized['business']['steps'], [])
        self.assertIsNone(normalized['business']['current_step_id'])
        self.assertIsNone(normalized['business']['completion'])

    def test_invalid_step_update_preserves_last_valid_steps_and_recovers(self):
        raw = projection()
        raw['business'].update(steps=[{'step_id': 'EXPORT', 'state': 'UNKNOWN', 'depends_on': []}],
                               current_step_id='EXPORT')
        source = Source(raw)
        service = self.observer({'one': {'selection': identity(), 'reader': source.read}}, poll_seconds=.02)
        before = service.snapshot('one')
        wrong = deepcopy(raw); wrong['business']['steps'][0]['depends_on'] = ['MISSING']
        source.set(wrong)
        self.eventually(lambda: 'SOURCE_UNAVAILABLE' in service.snapshot('one')['observation']['gaps'])
        self.assertEqual(service.snapshot('one')['business'], before['business'])
        restored = deepcopy(raw)
        restored['business']['steps'][0]['state'] = 'ACCEPTED'
        restored['business']['current_step_id'] = None
        source.set(restored)
        self.eventually(lambda: not service.snapshot('one')['observation']['gaps'])
        self.assertEqual(service.snapshot('one')['business']['steps'][0]['state'], 'ACCEPTED')
        self.assertIsNone(service.snapshot('one')['business']['current_step_id'])
        self.assertEqual(service.snapshot('one')['business']['budget'], before['business']['budget'])

    def test_two_cached_views_do_not_collect_again_and_copy_is_detached(self):
        service = self.observer(poll_seconds=60)
        calls = self.source.calls
        snap = service.snapshot('one')
        snap['business']['title'] = 'changed by caller'
        for _ in range(3):
            self.assertEqual(self.request(service, 'api/snapshot?run=one')[0], 200)
        _, a = self.subscribe(service)
        _, b = self.subscribe(service)
        self.assertEqual(self.event(a), self.event(b))
        self.assertEqual(self.source.calls, calls)
        self.assertNotEqual(service.snapshot('one')['business']['title'], snap['business']['title'])

    def test_same_run_id_different_project_version_and_prepared_are_isolated(self):
        first = identity('a', '1')
        second = identity('a', '2')
        first.update(kind='foundry_build', program_id='program-a', prepared_event_id='p1')
        second.update(kind='foundry_build', program_id='program-a', prepared_event_id='p2')
        a, b = Source(projection(first)), Source(projection(second))
        b.data['business']['budget']['attempts_consumed'] = 7
        service = self.observer({'one': {'selection': first, 'reader': a.read},
                                 'two': {'selection': second, 'reader': b.read}}, poll_seconds=60)
        self.assertEqual(service.snapshot('one')['selection'], first)
        self.assertEqual(service.snapshot('two')['selection'], second)
        self.assertEqual(service.snapshot('one')['business']['budget']['attempts_consumed'], 2)
        self.assertEqual(service.snapshot('two')['business']['budget']['attempts_consumed'], 7)
        for run, expected in (('one', first), ('two', second)):
            _, response = self.subscribe(service, run)
            self.assertEqual(self.event(response)['selection'], expected)

    def test_only_prepared_differs_snapshots_and_subscriptions_keep_scopes_separate(self):
        first = identity('a', '1', 'run-a')
        first.update(kind='foundry_build', program_id='program-a', prepared_event_id='p1')
        second = dict(first, prepared_event_id='p2')
        first_data, second_data = projection(first), projection(second)
        first_data['business']['scope_ref'] = 'scope-p1'
        second_data['business']['scope_ref'] = 'scope-p2'
        second_data['business']['budget'] = {'attempts_consumed': 7, 'attempts_remaining': 1}
        second_data['business']['items'][0]['evidence_refs'] = ['receipt-p2']
        a, b = Source(first_data), Source(second_data)
        service = self.observer({'one': {'selection': first, 'reader': a.read},
                                 'two': {'selection': second, 'reader': b.read}}, poll_seconds=60)
        calls = (a.calls, b.calls)
        for local_id, selected, scope, budget, receipts in (
                ('one', first, 'scope-p1', {'attempts_consumed': 2, 'attempts_remaining': 3}, ['receipt-1']),
                ('two', second, 'scope-p2', {'attempts_consumed': 7, 'attempts_remaining': 1}, ['receipt-p2'])):
            status, _, body = self.request(service, 'api/snapshot?run=' + local_id)
            self.assertEqual(status, 200)
            snapshot = json.loads(body)
            self.assertEqual(snapshot['selection'], selected)
            self.assertEqual(snapshot['business']['scope_ref'], scope)
            self.assertEqual(snapshot['business']['budget'], budget)
            self.assertEqual(snapshot['business']['items'][0]['evidence_refs'], receipts)
            for _ in range(2):
                _, response = self.subscribe(service, local_id, headers={'Last-Event-ID': 'old-session:99'})
                self.assertEqual(self.event(response), snapshot)
        self.assertEqual((a.calls, b.calls), calls)

    def test_wrong_prepared_source_retains_old_scope_and_recovers_without_affecting_other(self):
        first = identity('a', '1', 'run-a')
        first.update(kind='foundry_build', program_id='program-a', prepared_event_id='p1')
        second = dict(first, prepared_event_id='p2')
        first_data, second_data = projection(first), projection(second)
        first_data['business']['scope_ref'] = 'scope-p1'
        second_data['business']['scope_ref'] = 'scope-p2'
        second_data['business']['budget'] = {'attempts_consumed': 7, 'attempts_remaining': 1}
        a, b = Source(first_data), Source(second_data)
        service = self.observer({'one': {'selection': first, 'reader': a.read},
                                 'two': {'selection': second, 'reader': b.read}}, poll_seconds=.02)
        before = service.snapshot('one')
        wrong = deepcopy(first_data)
        wrong['selection']['prepared_event_id'] = 'p2'
        wrong['business']['scope_ref'] = 'wrong-scope'
        wrong['business']['budget'] = {'attempts_consumed': 99, 'attempts_remaining': 0}
        a.set(wrong)
        self.eventually(lambda: 'SOURCE_UNAVAILABLE' in service.snapshot('one')['observation']['gaps'])
        _, response = self.subscribe(service, 'one')
        retained = self.event(response)
        self.assertEqual(retained['selection'], first)
        self.assertEqual(retained['business'], before['business'])
        self.assertIn('SOURCE_UNAVAILABLE', retained['observation']['gaps'])
        self.assertEqual(service.snapshot('two')['business']['scope_ref'], 'scope-p2')
        self.assertEqual(service.snapshot('two')['business']['budget'], {'attempts_consumed': 7, 'attempts_remaining': 1})
        self.assertFalse(service.snapshot('two')['observation']['gaps'])
        restored = deepcopy(first_data)
        restored['business']['source_revision'] = 2
        restored['business']['budget'] = {'attempts_consumed': 3, 'attempts_remaining': 2}
        a.set(restored)
        self.eventually(lambda: service.snapshot('one')['business']['source_revision'] == 2)
        _, recovered_response = self.subscribe(service, 'one')
        recovered = self.event(recovered_response)
        self.assertEqual(recovered['selection'], first)
        self.assertEqual(recovered['business']['scope_ref'], 'scope-p1')
        self.assertEqual(recovered['business']['budget'], {'attempts_consumed': 3, 'attempts_remaining': 2})
        self.assertFalse(recovered['observation']['gaps'])
        self.assertEqual(service.snapshot('two')['business']['budget'], {'attempts_consumed': 7, 'attempts_remaining': 1})

    def test_unchanged_revision_updates_activity_and_invalidated_completion(self):
        service = self.observer(poll_seconds=.02)
        before = service.snapshot('one')
        changed = projection()
        changed['observation']['activity']['last_output_at'] = '2026-10-17T10:01:02Z'
        changed['business']['completion'] = {'completed': 1, 'total': 1, 'label': '已验成果'}
        self.source.set(changed)
        self.eventually(lambda: service.snapshot('one')['business']['completion'])
        changed['business']['completion']['completed'] = 0
        changed['business']['items'][0]['state'] = 'INVALIDATED'
        self.source.set(changed)
        self.eventually(lambda: service.snapshot('one')['business']['items'][0]['state'] == 'INVALIDATED')
        after = service.snapshot('one')
        self.assertEqual(after['business']['source_revision'], before['business']['source_revision'])
        self.assertEqual(after['business']['completion']['completed'], 0)
        self.assertEqual(after['business']['budget']['attempts_consumed'], 2)
        self.assertNotEqual(after['observation']['activity'], before['observation']['activity'])

    def test_read_failure_preserves_last_valid_and_recovers_without_source_write(self):
        service = self.observer(poll_seconds=.02)
        before = service.snapshot('one')
        self.source.error = OSError('/private/token-SECRET cannot read')
        self.eventually(lambda: service.snapshot('one')['observation']['gaps'])
        bad = service.snapshot('one')
        self.assertEqual(bad['business'], before['business'])
        self.assertNotIn('SECRET', json.dumps(bad))
        self.assertIsNotNone(bad['observation']['observed_at'])
        self.source.error = None
        self.eventually(lambda: not service.snapshot('one')['observation']['gaps'])
        self.assertEqual(service.snapshot('one')['business'], before['business'])

    def test_wrong_source_identity_does_not_replace_previous_scope(self):
        service = self.observer(poll_seconds=.02)
        self.source.set(projection(identity('wrong')))
        self.eventually(lambda: service.snapshot('one')['observation']['gaps'])
        self.assertEqual(service.snapshot('one')['selection'], identity())
        self.assertEqual(service.snapshot('one')['business']['scope_ref'], 'scope-1')

    def test_initial_unavailable_source_is_unknown_and_not_success(self):
        source = Source()
        source.error = OSError('SECRET')
        service = self.observer({'one': {'selection': identity(), 'reader': source.read}})
        state = service.snapshot('one')
        self.assertIsNone(state['business']['completion'])
        self.assertTrue(state['observation']['gaps'])
        self.assertNotIn('SECRET', json.dumps(state))

    def test_subscription_handshake_closes_snapshot_gap_and_reconnect_gets_latest(self):
        service = self.observer(poll_seconds=.02)
        old = service.snapshot('one')
        changed = projection()
        changed['business']['source_revision'] = 2
        self.source.set(changed)
        self.eventually(lambda: service.snapshot('one')['business']['source_revision'] == 2)
        conn, response = self.subscribe(service, headers={'Last-Event-ID': 'retired-session:9999'})
        first = self.event(response)
        self.assertEqual(first['business']['source_revision'], 2)
        self.assertGreater(first['transport']['sequence'], old['transport']['sequence'])
        response.close()
        conn.close()
        changed['business']['source_revision'] = 3
        self.source.set(changed)
        self.eventually(lambda: service.snapshot('one')['business']['source_revision'] == 3)
        _, second = self.subscribe(service)
        self.assertEqual(self.event(second)['business']['source_revision'], 3)

    def test_stopping_one_view_does_not_stop_other_or_trigger_another_collector(self):
        service = self.observer(poll_seconds=.02, heartbeat_seconds=.02, idle_seconds=.1)
        conn, first = self.subscribe(service)
        _, second = self.subscribe(service)
        self.event(first)
        self.event(second)
        first.close()
        conn.close()
        changed = projection()
        changed['business']['source_revision'] = 8
        self.source.set(changed)
        deadline = time.monotonic() + 3
        while self.event(second)['business']['source_revision'] != 8:
            self.assertLess(time.monotonic(), deadline)
        self.assertFalse(service.wait(.15))

    def test_idle_stop_and_explicit_stop_release_only_own_socket(self):
        other = socket.socket()
        other.bind(('127.0.0.1', 0))
        other.listen()
        self.addCleanup(other.close)
        service = self.observer(poll_seconds=.02, idle_seconds=.08)
        port = service.bound_port
        self.assertTrue(service.wait(3))
        service.stop()
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=.2)
        self.assertGreater(other.getsockname()[1], 0)

    def test_active_subscription_prevents_idle_and_restart_has_new_transport_session(self):
        service = self.observer(poll_seconds=.02, heartbeat_seconds=.02, idle_seconds=.1)
        _, response = self.subscribe(service)
        first = self.event(response)
        self.assertFalse(service.wait(.15))
        service.stop()
        new = self.observer(poll_seconds=60)
        self.assertNotEqual(first['transport']['session_id'], new.snapshot('one')['transport']['session_id'])
        self.assertEqual(first['business'], new.snapshot('one')['business'])

    def test_routes_are_loopback_read_only_fixed_assets_no_path_browser(self):
        service = self.observer(poll_seconds=60)
        self.assertEqual(urlsplit(service.url).hostname, '127.0.0.1')
        for route in ('', 'app.js', 'style.css', 'api/runs'):
            status, headers, body = self.request(service, route)
            self.assertEqual(status, 200, route)
            self.assertTrue(body)
            self.assertNotIn('Access-Control-Allow-Origin', headers)
        for route in ('../capability.json', '%2e%2e/capability.json', 'api/execute', 'api/snapshot?run=other'):
            self.assertGreaterEqual(self.request(service, route)[0], 400)
        self.assertGreaterEqual(self.request(service, 'api/runs', method='POST')[0], 400)
        self.assertGreaterEqual(self.request(service, 'api/runs', headers={'Host': 'evil.invalid'})[0], 400)
        self.assertGreaterEqual(self.request(service, 'api/runs', headers={'Origin': 'https://evil.invalid'})[0], 400)
        url = urlsplit(service.url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
        conn.request('GET', '/api/runs')
        response = conn.getresponse()
        self.assertGreaterEqual(response.status, 400)
        response.read()
        conn.close()

    def test_host_can_stop_during_first_bounded_read_without_deadlocking(self):
        entered, release = threading.Event(), threading.Event()
        def read():
            entered.set()
            release.wait(3)
            return projection()
        service = D.Observer({'one': {'selection': identity(), 'reader': read}})
        self.addCleanup(service.stop)
        starter = threading.Thread(target=service.start, daemon=True)
        starter.start()
        self.assertTrue(entered.wait(2))
        stopper = threading.Thread(target=service.stop, daemon=True)
        stopper.start()
        try:
            self.assertTrue(service.wait(2))
        finally:
            release.set()
            starter.join(2)
            stopper.join(2)
        self.assertFalse(starter.is_alive())
        self.assertFalse(stopper.is_alive())

    def test_stop_closes_incomplete_http_connection_and_own_handlers(self):
        service = self.observer(poll_seconds=60)
        client = socket.create_connection(('127.0.0.1', service.bound_port), timeout=2)
        self.addCleanup(client.close)
        client.sendall(b'GET / HTTP/1.1\r\n')
        service.stop()
        try:
            self.assertEqual(client.recv(1), b'')
        except ConnectionResetError:
            pass
        self.assertFalse(any(t.is_alive() and service.session_id in t.name
                             for t in threading.enumerate()))

    def test_multiple_names_for_same_selection_do_not_create_duplicate_collectors(self):
        source = Source()
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_SELECTION'):
            D.Observer({key: {'selection': identity(), 'reader': source.read}
                        for key in ('one', 'alias')})
        self.assertEqual(source.calls, 0)

    def test_idle_rechecks_new_activity_before_claiming_stop(self):
        service = self.observer(poll_seconds=60, idle_seconds=60)
        service._last_activity = time.monotonic() - 100
        service._touch()
        service._stop(only_if_idle=True)
        self.assertTrue(service.running)
        self.assertEqual(self.request(service, 'api/runs')[0], 200)
        service._last_activity = time.monotonic() - 100
        service._stop(only_if_idle=True)
        self.assertTrue(service.wait(2))

    def test_initial_read_time_does_not_spend_viewers_first_idle_period(self):
        def slow_first_read():
            time.sleep(.15)
            return projection()
        service = self.observer({'one': {'selection': identity(), 'reader': slow_first_read}},
                                poll_seconds=60, idle_seconds=.1)
        self.assertFalse(service.wait(.04))
        self.assertEqual(self.request(service, 'api/runs')[0], 200)
        self.assertTrue(service.wait(3))


class DashboardDeliveryTests(unittest.TestCase):
    def test_prepare_consume_binds_all_runtime_assets_and_preserves_venv(self):
        spec = importlib.util.spec_from_file_location('wp05_consume', ROOT / 'examples/capability-adapters/consume.py')
        consume = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consume)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / 'selected'
            shutil.copytree(PACKAGE, package)
            config = {'project_root': str(root / 'project'),
                      'selections': [{'directory': str(package), 'version': '1'}],
                      'environment_bindings': {'python': {'path': sys.executable,
                          'observed_version': '.'.join(map(str, sys.version_info[:3]))}}}
            (root / 'project').mkdir()
            materials, _ = consume._prepare.build_materials(config, root / 'materials')
            call = consume.prepare_call(materials, 'local-dashboard', ['--help'])
            self.assertEqual(call['argv'][0], sys.executable)
            self.assertFalse(call['commands_executed'])
            selected = {row['path'] for row in materials['preparation']['selections'][0]['files']}
            self.assertTrue({'capability.json', 'dashboard.py', 'web/index.html', 'web/app.js', 'web/style.css'} <= selected)
            result = subprocess.run(call['argv'], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            (package / 'web/app.js').write_text('changed selected view')
            with self.assertRaisesRegex(ValueError, 'selected capability files changed'):
                consume.prepare_call(materials, 'local-dashboard', ['--help'])
            self.assertFalse(list((root / 'project').iterdir()))

    def test_cli_json_source_is_readonly_and_signal_cleans_observer_not_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'display.json'
            source.write_text(json.dumps(projection()))
            config = root / 'host.json'
            config.write_text(json.dumps({'runs': [{'id': 'one', 'selection': identity(), 'source': 'display.json'}]}))
            before = {p: p.read_bytes() for p in (source, config)}
            process = subprocess.Popen([sys.executable, '-I', '-B', str(PACKAGE / 'dashboard.py'),
                '--config', str(config), '--poll-seconds', '0.02', '--idle-seconds', '0'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 5)[0], 'CLI did not announce URL')
                line = process.stdout.readline()
                self.assertTrue(line, process.stderr.read() if process.poll() is not None else 'no URL')
                startup = json.loads(line)
                url = urlsplit(startup['url'])
                conn = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
                conn.request('GET', url.path + 'api/snapshot?run=one')
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                state = json.loads(response.read())
                conn.close()
                self.assertEqual(state['business']['title'], projection()['business']['title'])
                process.terminate()
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                with self.assertRaises(OSError):
                    socket.create_connection((url.hostname, url.port), timeout=.2)
                self.assertEqual(before, {p: p.read_bytes() for p in before})
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
