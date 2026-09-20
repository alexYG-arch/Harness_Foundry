"""Durable real-process fixtures. No model invocation or sandbox qualification."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.local_process import CodexSandboxRunner
from harness_foundry_factory.process_observation import CommandObservation
from test_coding_protocol import EVENTS, capture


class ProcessObservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def test_full_durable_stream_recovers_after_result_delivery_is_lost(self):
        journal = CommandObservation(self.root / "command", "TEST-COMMAND", "CODEX")
        message = {"type": "item.completed", "item": {"type": "agent_message", "text": "中" * 30000}}
        data = capture(EVENTS[:2] + [message] + EVENTS[2:])
        try:
            result = CodexSandboxRunner("/usr/bin/true")._capture(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                self.root, 5, stdin_bytes=data, on_started=journal.started,
                stream_sink=journal.write, on_capture=journal.captured)
        finally:
            journal.close()
        self.assertTrue(result["output_truncated"])
        self.assertFalse((journal.root / "result.json").exists(), "simulate crash before returning the final result")
        recovered = CommandObservation.recover(journal.root, "TEST-COMMAND", "CODEX")
        self.assertEqual(recovered["status"], "MODEL_TURN_COMPLETED")
        self.assertFalse(recovered["workpack_accepted"])
        self.assertEqual((journal.root / "stdout.bin").read_bytes(), data)

    def test_partial_capture_or_wrong_binding_never_recovers_completion(self):
        journal = CommandObservation(self.root / "partial", "TEST-COMMAND", "CODEX")
        journal.write("stdout", capture(EVENTS))
        journal.close()
        self.assertIsNone(CommandObservation.recover(journal.root, "TEST-COMMAND", "CODEX"))
        with self.assertRaises(ValueError):
            CommandObservation.recover(journal.root, "ANOTHER-COMMAND", "CODEX")

    def test_missing_durable_bytes_do_not_recover_even_with_capture_metadata(self):
        journal = CommandObservation(self.root / "short", "TEST-COMMAND", "CODEX")
        journal.captured({"exit_code": 0, "timed_out": False, "stream_bytes": {"stdout": 100}})
        journal.close()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            CommandObservation.recover(journal.root, "TEST-COMMAND", "CODEX")

    def test_result_attachment_is_not_an_acceptance_record(self):
        journal = CommandObservation(self.root / "local", "TEST-COMMAND", "LOCAL")
        journal.finished({"status": "PASS", "exit_code": 0})
        journal.close()
        self.assertEqual(CommandObservation.recover(journal.root, "TEST-COMMAND", "LOCAL"),
                         {"status": "PASS", "exit_code": 0})
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["local"])

    def test_live_pid_is_diagnostic_not_identity_or_replay_authority(self):
        journal = CommandObservation(self.root / "running", "TEST-COMMAND", "LOCAL")
        journal.started(os.getpid())
        result = CommandObservation.inspect(journal.root)
        self.assertEqual(result["process_probe"], "PID_PRESENT_IDENTITY_UNCONFIRMED")
        self.assertFalse(result["replay_allowed"])
        self.assertIsNone(CommandObservation.recover(journal.root, "TEST-COMMAND", "LOCAL"))
        with patch("harness_foundry_factory.process_observation.os.kill", side_effect=ProcessLookupError):
            absent = CommandObservation.inspect(journal.root)
        self.assertEqual(absent["process_probe"], "PID_ABSENT_EFFECTS_UNKNOWN")
        self.assertFalse(absent["replay_allowed"])


if __name__ == "__main__":
    unittest.main()
