"""Version 4 display engineering tests; native browser verification is separate."""
from contextlib import redirect_stdout
from copy import deepcopy
import http.client
import importlib.util
from io import StringIO
import json
from pathlib import Path
import shutil
import socket
import subprocess
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import test_capability_dashboard as fixture
import test_foundry_dashboard_host as host_fixture
import test_dashboard_workflow_ui as workflow_fixture

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'examples/capability-adapters/packages/local-dashboard/4'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D = load('display_dashboard4', PACKAGE / 'dashboard.py')
T = load('display_target4', PACKAGE / 'target.py')
OLD = load('display_dashboard3', PACKAGE.with_name('3') / 'dashboard.py')


class DashboardDisplayTests(unittest.TestCase):
    def service(self):
        source = fixture.Source()
        observer = D.Observer({'one': {'selection': fixture.identity(), 'reader': source.read}},
                              poll_seconds=60, idle_seconds=0)
        self.addCleanup(observer.stop)
        return source, observer

    def get(self, url):
        parsed = urlsplit(url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''))
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_new_urls_share_observer_cache_and_leave_business_untouched(self):
        source, observer = self.service()
        original = deepcopy(source.data)
        self.assertEqual(observer.view_urls, {})
        with patch('subprocess.Popen', side_effect=AssertionError('must not dispatch')):
            observer.start()
            self.assertEqual(observer.view_urls, {'embedded': observer.url + '?view=embedded',
                                                  'browser': observer.url + '?view=browser'})
            self.assertEqual(observer.component, {'id': 'local-dashboard', 'version': '4'})
            bodies = [self.get(url) for url in observer.view_urls.values()]
            self.assertEqual(bodies[0], bodies[1])
            self.assertEqual(bodies[0][0], 200)
            self.assertIn(b'fullscreen-button', bodies[0][1])
            self.assertNotIn(b'sidebar-button', bodies[0][1])
            first = json.loads(self.get(observer.url + 'api/snapshot?run=one')[1])
            second = json.loads(self.get(observer.url + 'api/snapshot?run=one')[1])
            self.assertEqual(first, second)
            self.assertEqual(first['business']['budget'], original['business']['budget'])
            self.assertEqual(source.calls, 1)
            self.assertEqual(source.data, original)
            port = observer.bound_port
            observer.stop()
            self.assertTrue(observer.wait(1))
            self.assertEqual(observer.view_urls, {})
            with self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', port), timeout=.2)

    def test_display_version_preserves_normalized_progress_and_legacy_package(self):
        raw = workflow_fixture.extended()
        self.assertEqual(D.normalize_projection(raw, raw['selection']),
                         OLD.normalize_projection(raw, raw['selection']))
        with OLD.Observer({'one': {'selection': fixture.identity(), 'reader': fixture.Source().read}},
                          poll_seconds=60) as old:
            self.assertEqual(old.component['version'], '3')
            self.assertFalse(hasattr(old, 'view_urls'))
            self.assertIn(b'sidebar-button', self.get(old.url)[1])

    def test_three_launch_entries_report_urls_without_opening_apps(self):
        for module in (D, T, host_fixture.HOST):
            with self.subTest(module=module.__name__):
                _, observer = self.service()
                output = StringIO()
                with patch.object(module, 'observer_from_config', return_value=observer), \
                     patch.object(observer, 'wait', return_value=True), \
                     patch('subprocess.Popen', side_effect=AssertionError('must not open apps')), \
                     redirect_stdout(output):
                    self.assertEqual(module.main(['--config', 'fixture.json']), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report['view_urls'], {'embedded': report['url'] + '?view=embedded',
                                                       'browser': report['url'] + '?view=browser'})
                self.assertEqual(report['session_id'], observer.session_id)
                self.assertEqual(observer.view_urls, {})

    def test_foundry_host_old_selection_keeps_original_launch_report(self):
        observer = OLD.Observer({'one': {'selection': fixture.identity(), 'reader': fixture.Source().read}},
                               poll_seconds=60, idle_seconds=0)
        self.addCleanup(observer.stop)
        output = StringIO()
        with patch.object(host_fixture.HOST, 'observer_from_config', return_value=observer), \
             patch.object(observer, 'wait', return_value=True), redirect_stdout(output):
            self.assertEqual(host_fixture.HOST.main(['--config', 'fixture.json']), 0)
        self.assertEqual(set(json.loads(output.getvalue())), {'url', 'component', 'session_id'})

    def run_dom(self, group):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node unavailable; DOM engineering verification not run')
        result = subprocess.run([node, str(ROOT / 'tests/fixtures/dashboard_display_dom.js'),
                                 str(PACKAGE / 'web/app.js'), group],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS', result.stdout)

    def test_embedded_and_capability_detection(self): self.run_dom('availability')
    def test_fullscreen_enter_exit_escape_and_failure(self): self.run_dom('fullscreen')
    def test_pip_fullscreen_transition_and_pending_request(self): self.run_dom('pip_transition')
    def test_same_state_history_reconnect_and_prepared_isolation(self): self.run_dom('shared_state')
    def test_human_labels_keep_acceptance_and_unknown_boundaries(self): self.run_dom('wording')


if __name__ == '__main__':
    unittest.main()
