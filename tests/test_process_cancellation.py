"""Real finite local processes; no model, OS sandbox or real user approval."""

from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from harness_foundry_factory.local_process import CodexSandboxRunner, classify_local_capture
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.coding_events import CodingEventObserver
from harness_foundry_factory.coding_process import classify_coding_capture


class ProcessCancellationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runner = CodexSandboxRunner("/usr/bin/true")

    def test_cancel_kills_owned_group_retains_partial_bytes_and_recovers_as_unknown(self):
        child = "import time; from pathlib import Path; time.sleep(1); Path('late').write_text('bad')"
        code = ("import subprocess,time; from pathlib import Path; "
                f"subprocess.Popen([{sys.executable!r}, '-c', {child!r}]); "
                "Path('ready').write_text('partial'); print('started', flush=True); time.sleep(10)")
        observation = CommandObservation(self.root / "observation", "TEST-COMMAND", "LOCAL")
        try:
            capture = self.runner._capture([sys.executable, "-c", code], self.root, 5,
                cancellation_reason=lambda: "BUILD_AUTHORIZATION_REVOKED" if (self.root / "ready").exists() else None,
                on_started=observation.started, stream_sink=observation.write, on_capture=observation.captured)
        finally:
            observation.close()
        result = classify_local_capture(capture)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(result["reason_code"], "LOCAL_PROCESS_CANCELLED")
        self.assertEqual(result["cancellation_reason"], "BUILD_AUTHORIZATION_REVOKED")
        self.assertFalse(result["timed_out"])
        self.assertEqual((self.root / "ready").read_text(), "partial")
        self.assertIn("started", result["stdout"])
        self.assertEqual(CommandObservation.recover(self.root / "observation", "TEST-COMMAND", "LOCAL"), result)
        time.sleep(1.1)  # The cancelled descendant must not create its delayed output.
        self.assertFalse((self.root / "late").exists())

    def test_closed_output_pipes_do_not_disable_cancellation_until_timeout(self):
        code = ("import os,time; from pathlib import Path; os.close(1); os.close(2); "
                "Path('ready').write_text('started'); time.sleep(10)")
        started = time.monotonic()
        capture = self.runner._capture([sys.executable, "-c", code], self.root, 5,
            cancellation_reason=lambda: "BUILD_AUTHORIZATION_EXPIRED" if (self.root / "ready").exists() else None)
        self.assertLess(time.monotonic() - started, 4)
        self.assertFalse(capture["timed_out"])
        self.assertEqual(capture["cancellation_reason"], "BUILD_AUTHORIZATION_EXPIRED")

    def test_unavailable_authority_monitor_stops_and_is_not_retryable_business_failure(self):
        def unavailable():
            if (self.root / "ready").exists():
                raise OSError("TEST controller unavailable")
        code = "import time; from pathlib import Path; Path('ready').touch(); time.sleep(10)"
        capture = self.runner._capture([sys.executable, "-c", code], self.root, 5,
                                      cancellation_reason=unavailable)
        result = classify_local_capture(capture)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(result["cancellation_reason"], "AUTHORIZATION_MONITOR_FAILED")
        self.assertIn("TEST controller unavailable", result["capture_error"])
        self.assertFalse(result["timed_out"])

    def test_current_authority_does_not_change_normal_completion(self):
        capture = self.runner._capture([sys.executable, "-c", "print('done')"], self.root, 5,
                                      cancellation_reason=lambda: None)
        self.assertEqual(classify_local_capture(capture)["status"], "PASS")
        self.assertFalse(capture.get("cancellation_reason"))
        self.assertEqual(capture["stdout"], "done\n")

    @unittest.skipUnless(os.name == "posix", "owned process groups require POSIX")
    def test_parent_sigint_persists_real_exit_before_propagating_and_recovery_does_not_replay(self):
        # The receiver host itself is interrupted, rather than a child merely
        # returning exit 130. All processes here are finite local Python probes.
        child = "import time; from pathlib import Path; time.sleep(1); Path('late').write_text('bad')"
        workload = (
            "import os,signal,subprocess,time; from pathlib import Path; "
            f"subprocess.Popen([{sys.executable!r}, '-c', {child!r}]); "
            "Path('started-once').write_text('1'); print('partial', flush=True); "
            "time.sleep(0.2); os.kill(os.getppid(), signal.SIGINT); time.sleep(10)"
        )
        host = (
            "from pathlib import Path\n"
            "from harness_foundry_factory.local_process import CodexSandboxRunner\n"
            "from harness_foundry_factory.process_observation import CommandObservation\n"
            f"root = Path({str(self.root)!r})\n"
            "observation = CommandObservation(root / 'observation', 'TEST-COMMAND', 'LOCAL')\n"
            "try:\n"
            f"    CodexSandboxRunner('/usr/bin/true')._capture([{sys.executable!r}, '-c', {workload!r}], root, 5, "
            "on_started=observation.started, stream_sink=observation.write, on_capture=observation.captured)\n"
            "except KeyboardInterrupt:\n"
            "    (root / 'propagated').write_text('KeyboardInterrupt')\n"
            "    raise\n"
            "finally:\n"
            "    observation.close()\n"
        )
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
                       "PYTHONDONTWRITEBYTECODE": "1"}
        process = subprocess.run([sys.executable, "-c", host], cwd=self.root,
                                 env=environment, capture_output=True, timeout=10)
        self.assertIn(process.returncode, (-signal.SIGINT, 130))
        self.assertEqual((self.root / "propagated").read_text(), "KeyboardInterrupt")
        capture = json.loads((self.root / "observation" / "capture.json").read_text())
        self.assertEqual(capture["exit_code"], -signal.SIGKILL)
        self.assertEqual(capture["cancellation_reason"], "HOST_PROCESS_INTERRUPTED")
        self.assertEqual(capture["host_interruption"], "KeyboardInterrupt")
        self.assertIn("partial", capture["stdout"])
        self.assertEqual(capture["stream_bytes"]["stdout"],
                         (self.root / "observation" / "stdout.bin").stat().st_size)
        expected = classify_local_capture(capture)
        self.assertEqual(expected["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(expected["reason_code"], "LOCAL_PROCESS_CANCELLED")
        for _ in range(2):
            self.assertEqual(CommandObservation.recover(self.root / "observation", "TEST-COMMAND", "LOCAL"), expected)
        self.assertEqual((self.root / "started-once").read_text(), "1")
        time.sleep(1.1)
        self.assertFalse((self.root / "late").exists())

    def test_system_exit_from_host_callback_retains_capture_and_original_exit_code(self):
        observation = CommandObservation(self.root / "observation", "TEST-COMMAND", "LOCAL")
        def stop_host(chunk):
            raise SystemExit(23)
        try:
            with self.assertRaises(SystemExit) as raised:
                self.runner._capture([sys.executable, "-c", "import time; print('partial', flush=True); time.sleep(10)"],
                    self.root, 5, on_started=observation.started, stream_sink=observation.write,
                    on_stdout=stop_host, on_capture=observation.captured)
        finally:
            observation.close()
        self.assertEqual(raised.exception.code, 23)
        capture = json.loads((self.root / "observation" / "capture.json").read_text())
        self.assertEqual(capture["host_interruption"], "SystemExit")
        self.assertEqual(capture["exit_code"], -signal.SIGKILL)
        self.assertEqual(capture["stdout"], "partial\n")
        result = CommandObservation.recover(self.root / "observation", "TEST-COMMAND", "LOCAL")
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(result["reason_code"], "LOCAL_PROCESS_CANCELLED")

    def test_persistence_failure_does_not_swallow_host_interruption(self):
        received = []
        def stop_host(pid):
            raise KeyboardInterrupt()
        def cannot_persist(capture):
            received.append(capture)
            raise OSError("TEST unavailable observation store")
        with self.assertRaises(KeyboardInterrupt):
            self.runner._capture([sys.executable, "-c", "import time; time.sleep(10)"], self.root, 5,
                                 on_started=stop_host, on_capture=cannot_persist)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["exit_code"], -signal.SIGKILL)
        self.assertIn("CAPTURE_PERSISTENCE_FAILED", received[0]["capture_error"])
        self.assertEqual(classify_local_capture(received[0])["status"], "UNKNOWN_SIDE_EFFECT")

    def test_even_a_complete_terminal_cannot_override_observed_cancellation(self):
        observer = CodingEventObserver()
        observer.feed(b'{"type":"thread.started","thread_id":"TEST"}\n'
                      b'{"type":"turn.started"}\n{"type":"turn.completed"}\n')
        result = classify_coding_capture({"exit_code": 0, "timed_out": False,
            "cancellation_reason": "BUILD_AUTHORIZATION_EXPIRED"}, observer)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertEqual(result["reason_code"], "CODING_PROCESS_CANCELLED")


if __name__ == "__main__":
    unittest.main()
