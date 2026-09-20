"""Real finite local processes; no model, OS sandbox or real user approval."""

from pathlib import Path
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
