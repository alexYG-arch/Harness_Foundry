"""New correction rounds use existing dispatch/recovery, retaining original use."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import test_build_correction as correction
import test_build_runtime as support
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_runtime import revoke_build_authorization
from harness_foundry_factory.build_state import project_budget_attempts, attempt_budget, project_execution_state
from harness_foundry_factory.local_process import CodexSandboxRunner, classify_local_capture
from harness_foundry_factory.process_observation import CommandObservation


class CorrectionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.h = correction.CheckerCorrectionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.f = self.h.f

    def prepare(self, exhausted=False):
        self.h.prepare_failure(whole_budget=exhausted)
        self.old = self.f.prepared_id
        self.new, evidence = self.h.new_binding(complete=self.h.attempt_id)
        self.h.derive(self.new, evidence)

    def budget(self):
        return attempt_budget(self.f.scope, list(project_budget_attempts(self.f.events(), self.new).values()))

    def test_exhausted_production_can_finish_same_product_check(self):
        self.prepare(exhausted=True)
        start = len(self.h.runner.invocations)
        result = self.f.controller().advance(self.new, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result.get('attempt_status'), 'ACCEPTED', result)
        self.assertEqual([c['phase'] for c in self.h.runner.invocations[start:]], ['VERIFICATION'] * 2)
        self.assertEqual(self.budget()['attempts_consumed'], 1)
        self.assertEqual(self.budget()['attempts_remaining'], 0)
        self.assertEqual(self.budget()['checker_reverification_rounds'], 1)
        self.assertEqual(self.f.controller().advance(self.new)['status'], 'ATTEMPT_BUDGET_EXHAUSTED')
        self.assertEqual(project_budget_attempts(self.f.events(), self.new)[self.h.attempt_id]['status'], 'BLOCKED')

    def test_complete_new_capture_only_recovers_this_round(self):
        self.prepare(exhausted=True)
        start = len(self.h.runner.invocations)
        def crash(invocation, result):
            self.h.runner.after_run = None
            raise support.InjectedControllerCrash()
        self.h.runner.after_run = crash
        with self.assertRaises(support.InjectedControllerCrash):
            self.f.controller().advance(self.new, advance_mode='ONE_ATTEMPT')
        attempts, _ = project_execution_state(self.f.events(), self.new)
        child = next(iter(attempts))
        result = self.f.controller().advance(self.new, advance_mode='ONE_ATTEMPT')
        self.assertEqual((result.get('attempt_status'), result.get('attempt_id')), ('ACCEPTED', child), result)
        self.assertEqual([c['case_id'] for c in self.h.runner.invocations[start:]], ['READ-ROWS', 'REJECT-MALFORMED'])
        calls = len(self.h.runner.invocations)
        for _ in range(2):
            read_build(self.f.store.database_path, self.f.program)
        self.assertEqual(len(self.h.runner.invocations), calls)
        self.assertEqual(self.budget()['attempts_consumed'], 1)
        self.assertEqual(self.budget()['checker_reverification_rounds'], 1)

    def test_source_revocation_blocks_new_dispatch_keeps_old_readback(self):
        self.f.scope['expires_at'] = '2099-01-01T00:00:00Z'
        self.prepare()
        revoke_build_authorization(self.f.store, self.f.program, self.old, **self.f.kwargs('revoke-source'))
        calls = len(self.h.runner.invocations)
        result = self.f.controller().advance(self.new)
        self.assertEqual(result['status'], 'BUILD_STOPPED', result)
        self.assertIn('revoked', result['reason'])
        self.assertEqual(len(self.h.runner.invocations), calls)
        result = read_build(self.f.store.database_path, self.f.program)
        self.assertEqual(result['authorizations'][-1]['state'], 'REVOKED')
        self.assertEqual(self.budget()['attempts_consumed'], 1)

    def test_source_revocation_during_command_uses_existing_cancellation(self):
        # Real local process/cancellation proof, not native sandbox or model proof.
        self.prepare()
        captured = []
        processes = []
        observations = []
        popen = subprocess.Popen
        def record_process(*args, **kwargs):
            process = popen(*args, **kwargs)
            processes.append(process)
            return process
        def revoke_after_dispatch(invocation, before):
            before()
            self.assertEqual(invocation['executor'], 'LOCAL')
            journal = CommandObservation(invocation['observation_root'], invocation['command_id'], 'LOCAL',
                                         on_started=invocation['on_process_started'])
            observations.append((invocation, journal))
            def after_start(pid):
                journal.started(pid)
                revoke_build_authorization(self.f.store, self.f.program, self.old, **self.f.kwargs('revoke-in-command'))
            try:
                with patch('harness_foundry_factory.local_process.subprocess.Popen', side_effect=record_process):
                    capture = CodexSandboxRunner('/usr/bin/true')._capture(
                        [invocation['argv'][0], '-I', '-B', '-c', 'import time; time.sleep(20)'],
                        Path(invocation['cwd']), 5, on_started=after_start,
                        stream_sink=journal.write, on_capture=journal.captured,
                        cancellation_reason=invocation['cancellation_reason'])
                captured.append(capture)
                result = {**classify_local_capture(capture),
                          'receiver': 'TEST_ONLY_LOCAL_PROCESS_NOT_SANDBOX_QUALIFICATION'}
                journal.finished(result)
                return result
            finally:
                journal.close()
        self.f.runner = revoke_after_dispatch
        result = self.f.controller().advance(self.new, advance_mode='ONE_ATTEMPT')
        self.assertNotEqual(result.get('attempt_status'), 'ACCEPTED')
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]['cancellation_reason'], 'BUILD_AUTHORIZATION_REVOKED')
        self.assertFalse(captured[0]['timed_out'])
        self.assertIsNone(captured[0]['capture_error'])
        self.assertLess(captured[0]['exit_code'], 0)
        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0].poll(), captured[0]['exit_code'])
        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)
        invocation, journal = observations[0]
        recovered = CommandObservation.recover(journal.root, invocation['command_id'], 'LOCAL')
        self.assertEqual(recovered['cancellation_reason'], 'BUILD_AUTHORIZATION_REVOKED')
        self.assertEqual(recovered['reason_code'], 'LOCAL_PROCESS_CANCELLED')
        self.assertEqual(self.budget()['attempts_consumed'], 1)

    def test_before_first_command_reuses_same_round_including_real_preflight(self):
        for environment in (False, True):
            with self.subTest(environment=environment):
                if environment:
                    self.f.plan['schema_version'] = '1.1'
                    self.f.plan['workpacks'][0]['environment'] = {'python': 'python', 'modules': ['json'], 'paths': []}
                self.prepare(exhausted=True)
                controller = self.f.controller()
                append = controller._append
                def interrupt(kind, *args, **kwargs):
                    result = append(kind, *args, **kwargs)
                    if kind == 'BUILD_ATTEMPT_STARTED':
                        raise support.InjectedControllerCrash()
                    return result
                start = len(self.h.runner.invocations)
                with patch.object(controller, '_append', side_effect=interrupt), self.assertRaises(support.InjectedControllerCrash):
                    controller.advance(self.new, advance_mode='ONE_ATTEMPT')
                attempt_id = next(iter(project_execution_state(self.f.events(), self.new)[0]))
                result = self.f.controller().advance(self.new, advance_mode='ONE_ATTEMPT')
                self.assertEqual((result.get('attempt_id'), result.get('attempt_status')), (attempt_id, 'ACCEPTED'), result)
                self.assertEqual([c['phase'] for c in self.h.runner.invocations[start:]],
                                 (['PREFLIGHT'] if environment else []) + ['VERIFICATION'] * 2)
                self.assertEqual(self.budget()['checker_reverification_rounds'], 1)
                if not environment:
                    self.doCleanups()
                    self.setUp()


if __name__ == '__main__':
    unittest.main()
