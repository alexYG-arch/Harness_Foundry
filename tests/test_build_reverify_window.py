"""Accepted-byte binding across the preflight/input-record window.

Disposable Programs and actual local Python processes; no model or native sandbox claim.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_build_rebind as rebind_support
import test_build_runtime as support
from harness_foundry_factory.build_state import project_execution_state


class ReverificationWindowTests(unittest.TestCase):
    def setUp(self):
        self.h = rebind_support.RebindTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.f = self.h.f
        self.f.plan['schema_version'] = '1.1'
        self.f.plan['workpacks'][0]['environment'] = {'python': 'python', 'modules': ['json'], 'paths': []}
        self.f.prepare()
        self.assertEqual(self.f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
        self.product = self.f.workspace / 'src/reader.py'
        self.original = self.product.read_bytes()
        newroot = self.f.root / 'new-verifier'
        newroot.mkdir()
        (newroot / 'check.py').write_text(support.VERIFIER + '\n# updated checker binding\n')
        self.prepared = self.h.rebind(scope={**self.f.scope, 'verification_root': str(newroot)})
        self.calls_before = len(self.f.runner.invocations)

    def interrupt_before_inputs(self):
        controller = self.f.controller()
        append = controller._append
        def crash(kind, *args, **kwargs):
            if kind == 'BUILD_VERIFICATION_INPUTS':
                raise support.InjectedControllerCrash()
            return append(kind, *args, **kwargs)
        with patch.object(controller, '_append', side_effect=crash), self.assertRaises(support.InjectedControllerCrash):
            controller.advance(self.prepared, advance_mode='ONE_ATTEMPT')
        attempts, _ = project_execution_state(self.f.events(), self.prepared)
        return next(iter(attempts))

    def recover(self, fresh=False):
        if not fresh:
            return self.f.controller().advance(self.prepared, advance_mode='ONE_ATTEMPT')
        root = Path(__file__).resolve().parents[1]
        script = '''import json,os,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1]+'/src',sys.argv[1]+'/tests']
import test_build_runtime as support
from harness_foundry_factory.store import ControlEventStore
from harness_foundry_factory.build_runtime import BuildController
runner=support.FixtureProcessRunner()
store=ControlEventStore(Path(sys.argv[2]),storage_format='REVISION_V1')
result=BuildController(store,sys.argv[3],runner=runner,clock=support.CLOCK).advance(sys.argv[4],advance_mode='ONE_ATTEMPT')
print(json.dumps({'pid':os.getpid(),'result':result,'calls':runner.invocations},default=str))
'''
        run = subprocess.run([sys.executable, '-B', '-c', script, str(root), str(self.f.store.database_path),
                              self.f.program, self.prepared], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads(run.stdout)
        self.assertNotEqual(result['pid'], os.getpid())
        self.f.runner.invocations.extend(result['calls'])
        return result['result']

    def assert_same_accepted(self, result, attempt):
        self.assertEqual((result.get('attempt_status'), result.get('attempt_id')), ('ACCEPTED', attempt), result)
        self.assertEqual(self.h.budget(self.prepared)['attempts_consumed'], 3)
        attempts, _ = project_execution_state(self.f.events(), self.prepared)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.product.read_bytes(), self.original)
        self.assertEqual([x['phase'] for x in self.f.runner.invocations[self.calls_before:]],
                         ['PREFLIGHT', 'VERIFICATION', 'VERIFICATION'])

    def test_original_bytes_resume_same_attempt_after_preflight(self):
        attempt = self.interrupt_before_inputs()
        self.assert_same_accepted(self.recover(fresh=True), attempt)

    def changed_then_restored(self, *, fresh=False, missing=False):
        attempt = self.interrupt_before_inputs()
        if missing:
            self.product.unlink()
        else:
            self.product.write_bytes(self.original + b'\n# unbound new bytes\n')
        calls = len(self.f.runner.invocations)
        stopped = self.recover(fresh=fresh)
        self.assertEqual(stopped['status'], 'BUILD_STOPPED', stopped)
        self.assertEqual(len(self.f.runner.invocations), calls)
        self.assertEqual(self.h.budget(self.prepared)['attempts_consumed'], 3)
        self.assertFalse([e for e in self.f.events('BUILD_VERIFICATION_INPUTS')
                          if e['payload']['attempt_id'] == attempt])
        self.product.write_bytes(self.original)
        self.assert_same_accepted(self.recover(fresh=fresh), attempt)

    def test_changed_bytes_block_then_original_bytes_resume_same_attempt(self):
        self.changed_then_restored()

    def test_changed_bytes_block_then_restore_across_processes(self):
        self.changed_then_restored(fresh=True)

    def test_missing_bytes_do_not_discard_reverification_qualification(self):
        self.changed_then_restored(fresh=True, missing=True)

    def test_normal_path_rechecks_after_preflight_and_can_restore(self):
        def mutate(invocation, result):
            if invocation['phase'] == 'PREFLIGHT':
                self.f.runner.after_run = None
                self.product.write_bytes(self.original + b'\n# changed after first byte check\n')
        self.f.runner.after_run = mutate
        stopped = self.recover()
        self.assertNotEqual(stopped.get('attempt_status'), 'ACCEPTED', stopped)
        self.assertEqual([x['phase'] for x in self.f.runner.invocations[self.calls_before:]], ['PREFLIGHT'])
        attempts, _ = project_execution_state(self.f.events(), self.prepared)
        self.assertEqual(len(attempts), 1)
        attempt = next(iter(attempts))
        self.product.write_bytes(self.original)
        self.assert_same_accepted(self.recover(fresh=True), attempt)

    def test_existing_inputs_do_not_replay_completed_check(self):
        controller = self.f.controller()
        execute = controller._execute_command
        def crash(binding, prepared, invocation, revision):
            if invocation.get('case_id') == 'REJECT-MALFORMED':
                raise support.InjectedControllerCrash()
            return execute(binding, prepared, invocation, revision)
        with patch.object(controller, '_execute_command', side_effect=crash), self.assertRaises(support.InjectedControllerCrash):
            controller.advance(self.prepared, advance_mode='ONE_ATTEMPT')
        attempts, _ = project_execution_state(self.f.events(), self.prepared)
        attempt = next(iter(attempts))
        calls = len(self.f.runner.invocations)
        self.product.write_bytes(self.original + b'\n# changed during interruption\n')
        self.assertEqual(self.recover(fresh=True)['status'], 'BUILD_STOPPED')
        self.assertEqual(len(self.f.runner.invocations), calls)
        self.product.write_bytes(self.original)
        self.assert_same_accepted(self.recover(fresh=True), attempt)

    def test_legacy_inputs_different_from_accepted_bytes_are_not_reused(self):
        controller = self.f.controller()
        append = controller._append
        def old_input_observation(kind, payload, *args, **kwargs):
            if kind == 'BUILD_VERIFICATION_INPUTS':
                # Recreate the previous version's recorded observation in a new
                # fixture stream; neither old evidence nor SQLite is edited.
                self.product.write_bytes(self.original + b'\n# historical unbound bytes\n')
                payload = {**payload, 'artifacts': controller._artifacts(
                    self.f.workspace, self.f.plan['workpacks'][0]['artifacts'])}
                append(kind, payload, *args, **kwargs)
                raise support.InjectedControllerCrash()
            return append(kind, payload, *args, **kwargs)
        with patch.object(controller, '_append', side_effect=old_input_observation), self.assertRaises(support.InjectedControllerCrash):
            controller.advance(self.prepared, advance_mode='ONE_ATTEMPT')
        calls = len(self.f.runner.invocations)
        events = self.f.events()
        stopped = self.recover(fresh=True)
        self.assertEqual(stopped['status'], 'BUILD_STOPPED', stopped)
        self.assertIn('recorded reverification input differs', stopped['reason'])
        self.assertEqual(self.f.events(), events)
        self.assertEqual(len(self.f.runner.invocations), calls)
        self.assertEqual(self.h.budget(self.prepared)['attempts_consumed'], 3)

    def test_undeclared_file_change_does_not_block_reverification(self):
        attempt = self.interrupt_before_inputs()
        (self.f.workspace / 'unrelated.txt').write_text('unrelated authorized work')
        self.assert_same_accepted(self.recover(), attempt)


if __name__ == '__main__':
    unittest.main()
