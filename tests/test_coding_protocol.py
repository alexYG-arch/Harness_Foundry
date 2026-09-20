"""Offline fixtures of the documented Codex JSONL protocol, not model runs."""

from copy import deepcopy
import json
import subprocess
import sys
import unittest

from harness_foundry_factory.coding_protocol import CodingEventObserver, observe_coding_process


EVENTS = [
    {"type": "thread.started", "thread_id": "TEST-ONLY-THREAD"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "PASS"}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
]


def capture(events):
    return b"\n".join(json.dumps(event, ensure_ascii=False).encode("utf-8") for event in events) + b"\n"


class CodingProtocolTests(unittest.TestCase):
    def test_arbitrary_chunk_boundaries_do_not_corrupt_utf8_or_lifecycle(self):
        events = deepcopy(EVENTS)
        events[2]["item"]["text"] = "中文跨块"
        raw = capture(events)
        observer = CodingEventObserver()
        for byte in raw:
            observer.feed(bytes([byte]))
        result = observer.finish(exit_code=0)
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED")
        self.assertEqual(result["final_message"], "中文跨块")

    def test_event_limit_is_a_protocol_failure_not_a_display_limit(self):
        observer = CodingEventObserver(max_event_bytes=128)
        observer.feed(b"x" * 129)
        observer.feed(capture(EVENTS))
        self.assertEqual(observer.finish(exit_code=0)["reason_code"], "CODEX_EVENT_PROTOCOL_INVALID")
        self.assertEqual(len(observer.pending), 0)

    def test_complete_turn_is_not_a_workpack_or_schema_oracle_pass(self):
        result = observe_coding_process(capture(EVENTS), exit_code=0)
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED")
        self.assertEqual(result["final_message"], "PASS")
        self.assertEqual(result["thread_id"], "TEST-ONLY-THREAD")
        self.assertEqual(result["usage"], EVENTS[-1]["usage"])
        self.assertFalse(result["workpack_accepted"])
        self.assertFalse(result["automatic_retry_allowed"])

    def test_exit_zero_text_or_partial_events_cannot_claim_turn_completion(self):
        for output in (b"PASS\n", b"", b"{}\n", capture(EVENTS[:-1]), capture(EVENTS[1:]),
                       capture(EVENTS[2:]), b"\xff\n", capture([{"type": "unexpected.future.event"}])):
            with self.subTest(output=output):
                result = observe_coding_process(output, exit_code=0)
                self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
                self.assertFalse(result["automatic_retry_allowed"])

    def test_capture_loss_timeout_and_nonzero_exit_are_not_hidden_by_terminal_success(self):
        for options, expected in [({"exit_code": None}, "UNKNOWN_SIDE_EFFECT"),
                                  ({"exit_code": 1}, "MODEL_PROCESS_FAILED"),
                                  ({"exit_code": 0, "timed_out": True}, "UNKNOWN_SIDE_EFFECT"),
                                  ({"exit_code": 0, "output_truncated": True}, "UNKNOWN_SIDE_EFFECT")]:
            with self.subTest(options=options):
                result = observe_coding_process(capture(EVENTS), **options)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["workpack_accepted"])

    def test_single_attempt_does_not_accept_resume_second_turn_or_reordered_lifecycle(self):
        variants = [EVENTS + EVENTS, EVENTS + EVENTS[1:], EVENTS[:1] + EVENTS,
                    EVENTS[:2] + [EVENTS[-1]] + EVENTS[2:],
                    [{"type": "thread.started", "thread_id": ""}] + EVENTS[1:]]
        for events in variants:
            with self.subTest(events=events):
                result = observe_coding_process(capture(events), exit_code=0)
                self.assertEqual(result["reason_code"], "CODEX_EVENT_PROTOCOL_INVALID")

    def test_failure_events_are_recorded_even_if_the_process_exits_zero(self):
        failed = deepcopy(EVENTS)
        failed[-1] = {"type": "turn.failed", "error": {"message": "TEST ONLY failure"}}
        for events in (failed, EVENTS[:2] + [{"type": "error", "message": "TEST failure"}] + EVENTS[2:]):
            self.assertEqual(observe_coding_process(capture(events), exit_code=0)["status"], "MODEL_PROCESS_FAILED")

    def test_model_can_recover_a_tool_error_but_the_error_remains_visible_to_acceptance(self):
        events = EVENTS[:2] + [{"type": "item.completed", "item": {
            "id": "cmd1", "type": "command_execution", "status": "failed", "exit_code": 1}}] + EVENTS[2:]
        result = observe_coding_process(capture(events), exit_code=0)
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED")
        self.assertEqual(result["reported_command_failures"], [{"id": "cmd1", "exit_code": 1, "status": "failed"}])
        self.assertFalse(result["workpack_accepted"])

    def test_real_offline_process_capture_is_used_without_calling_codex_or_a_model(self):
        # This child only emits TEST JSON. It is a process/encoding test, not
        # evidence that a CLI service request or code generation succeeded.
        events = deepcopy(EVENTS)
        events[2]["item"]["text"] = "测试夹具，非生成结果"
        completed = subprocess.run([sys.executable, "-B", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                                   input=capture(events), capture_output=True, timeout=10)
        result = observe_coding_process(completed.stdout, exit_code=completed.returncode)
        self.assertEqual(result["final_message"], "测试夹具，非生成结果")
        self.assertFalse(result["workpack_accepted"])

    def test_invalid_capture_types_are_not_coerced_to_success(self):
        for output, options in [("not bytes", {"exit_code": 0}), (b"", {"exit_code": False}),
                                (b"", {"exit_code": 0, "timed_out": 0})]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                observe_coding_process(output, **options)


if __name__ == "__main__":
    unittest.main()
