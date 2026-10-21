"""WP06 host integration using isolated native records, not real-model/PiP acceptance."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import http.client
import importlib.util
import json
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from harness_foundry_factory.build_runtime import prepare_build_authorization
from harness_foundry_factory.revision_store import RevisionControlEventStore
import test_build_runtime as support


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'examples/capability-adapters/foundry_dashboard.py'
spec = importlib.util.spec_from_file_location('tested_foundry_dashboard_host', ENTRY)
HOST = importlib.util.module_from_spec(spec)
spec.loader.exec_module(HOST)


class FoundryDashboardHostTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.scope['expires_at'] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.f.prepare(approve=False)
        self.package = self.f.root / 'selected-dashboard'
        shutil.copytree(ROOT / 'examples/capability-adapters/packages/local-dashboard/1', self.package)
        consume = HOST._load(ROOT / 'examples/capability-adapters/consume.py', 'wp06_host_consume')
        materials, _ = consume._prepare.build_materials({
            'project_root': str(self.f.workspace),
            'selections': [{'directory': str(self.package), 'version': '1'}],
            'environment_bindings': {'python': {'path': sys.executable,
                'observed_version': '.'.join(map(str, sys.version_info[:3]))}},
        }, self.f.root / 'materials-output')
        (self.f.root / 'materials.json').write_text(json.dumps(materials))
        self.selection = dict(kind='foundry_build', project_id=self.f.ir['target']['id'],
            project_version='delivery-not-declared', run_id='same-run', program_id=self.f.program,
            prepared_event_id=self.f.prepared_id)
        self.config = self.f.root / 'observer.json'
        self.config_data = {'materials': 'materials.json', 'runs': [
            {'id': 'one', 'control_db': self.f.store.database_path.name, 'selection': self.selection}]}
        self.save()

    def save(self):
        self.config.write_text(json.dumps(self.config_data))

    def snapshot(self, url, run='one'):
        parsed = urlsplit(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        try:
            conn.request('GET', parsed.path + 'api/snapshot?run=' + run)
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            return json.loads(response.read())
        finally:
            conn.close()

    def test_selected_materials_and_two_prepared_scopes_share_cache_without_writes(self):
        other = prepare_build_authorization(self.f.store, self.f.program, self.f.proposal_id,
            self.f.source_id, self.f.scope, **self.f.kwargs('prepare-second'))
        second = dict(self.selection, prepared_event_id=other['event_id'])
        self.config_data['runs'].append(dict(id='two', control_db=self.f.store.database_path.name, selection=second))
        self.save()
        before = self.f.store.database_path.read_bytes()
        real_reader = HOST.read_foundry_projection
        with patch.object(HOST, 'read_foundry_projection', wraps=real_reader) as reader, \
                patch.object(RevisionControlEventStore, 'append_batch', side_effect=AssertionError('observer writes')), \
                patch('subprocess.Popen', side_effect=AssertionError('observer dispatch')):
            observer = HOST.observer_from_config(self.config, poll_seconds=60, idle_seconds=0)
            self.addCleanup(observer.stop)
            observer.start()
            calls = reader.call_count
            for _ in range(2):
                self.assertEqual(self.snapshot(observer.url)['selection'], self.selection)
                self.assertEqual(self.snapshot(observer.url, 'two')['selection'], second)
            self.assertEqual(reader.call_count, calls)
            self.assertEqual(calls, 2)
            self.assertEqual(self.snapshot(observer.url)['business']['budget']['attempts_consumed'], 0)
            observer.stop()
        self.assertEqual(self.f.store.database_path.read_bytes(), before)

    def test_changed_selected_assets_are_rejected_before_observer_start(self):
        (self.package / 'web/app.js').write_text('changed after selection')
        with patch.object(HOST, 'read_foundry_projection', side_effect=AssertionError('not started')), \
                self.assertRaisesRegex(ValueError, 'selected capability files changed'):
            HOST.observer_from_config(self.config)

    def test_in_process_host_cannot_silently_use_another_venv(self):
        other = self.f.root / 'other-venv' / 'bin' / 'python'
        other.parent.mkdir(parents=True)
        other.symlink_to(Path(sys.executable).resolve())
        with patch.object(HOST.sys, 'executable', str(other)), \
                patch.object(HOST, 'read_foundry_projection', side_effect=AssertionError('not started')), \
                self.assertRaisesRegex(ValueError, 'INTERPRETER_MISMATCH'):
            HOST.observer_from_config(self.config)

    def test_missing_prepared_never_falls_back_to_existing_scope(self):
        self.config_data['runs'][0]['selection']['prepared_event_id'] = 'CEVT-MISSING'
        self.save()
        with HOST.observer_from_config(self.config, poll_seconds=60) as observer:
            state = self.snapshot(observer.url)
            self.assertEqual(state['selection']['prepared_event_id'], 'CEVT-MISSING')
            self.assertIn('SOURCE_UNAVAILABLE', state['observation']['gaps'])
            self.assertIsNone(state['business']['completion'])
            self.assertNotIn('budget', state['business'])

    def test_repeated_cli_start_and_signal_stop_only_manage_observer(self):
        before = {p: p.read_bytes() for p in (self.config, self.f.store.database_path,
                                             self.f.root / 'materials.json')}
        sessions = []
        for _ in range(2):
            process = subprocess.Popen([sys.executable, '-I', '-B', str(ENTRY),
                '--config', str(self.config), '--poll-seconds', '0.05', '--idle-seconds', '0'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 8)[0], 'no startup output')
                startup = json.loads(process.stdout.readline())
                self.assertIn('url', startup)
                sessions.append(startup['session_id'])
                state = self.snapshot(startup['url'])
                self.assertEqual(state['selection'], self.selection)
                self.assertFalse(state['observation']['gaps'])
                self.assertEqual(state['business']['completion']['completed'], 0)
                process.terminate()
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                parsed = urlsplit(startup['url'])
                with self.assertRaises(OSError):
                    socket.create_connection((parsed.hostname, parsed.port), timeout=.2)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertNotEqual(*sessions)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse(self.f.runner.invocations)

    def test_bad_host_config_emits_no_private_path(self):
        private = self.f.root / 'PRIVATE-OBSERVER-CONFIG-NAME.json'
        private.write_text('{not json')
        result = subprocess.run([sys.executable, '-I', '-B', str(ENTRY), '--config', str(private)],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {'error': 'FOUNDRY_OBSERVER_START_FAILED'})
        self.assertNotIn(str(self.f.root), result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
