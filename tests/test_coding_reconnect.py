"""Offline protocol fixtures; no Codex service or Product Maker execution."""

import json
import unittest

from harness_foundry_factory.coding_events import CodingEventObserver, observe_coding_process


START = [{"type": "thread.started", "thread_id": "reconnect-fixture"}, {"type": "turn.started"}]
END = [{"type": "item.completed", "item": {"id": "answer", "type": "agent_message", "text": "done"}},
       {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 4}}]
RETRY = {"type": "error", "message": "Reconnecting... 1/5 (stream disconnected before completion: transport closed)"}


def raw(events):
    return b"\n".join(json.dumps(e, ensure_ascii=False).encode() for e in events) + b"\n"


def observe(middle=(), **options):
    return observe_coding_process(raw(START + list(middle) + END), **{"exit_code": 0, **options})


def operation(kind, identifier="cmd", item_type="command_execution", **values):
    return {"type": kind, "item": {"id": identifier, "type": item_type, **values}}


class CodingReconnectTests(unittest.TestCase):
    def assert_completed(self, result):
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED")
        self.assertFalse(result["workpack_accepted"])
        self.assertFalse(result["automatic_retry_allowed"])

    def test_native_retry_envelopes_allow_different_reasons(self):
        messages = [RETRY["message"],
                    "Reconnecting... 2/5 (timeout waiting for child process to exit)",
                    "Reconnecting... 1/5 (request timed out)",
                    "Reconnecting... 1/5 (upstream response:\nservice temporarily unavailable)",
                    "Reconnecting... 1/5", "Reconnecting... waiting for network",
                    "Reconnecting... waiting for network (connection failed)",
                    "Reconnecting... 100/100 (transport unavailable)",
                    "Reconnecting... 1/101 (transport unavailable)",
                    "Reconnecting... 1001/10000 (transport unavailable)"]
        for message in messages:
            with self.subTest(message=message):
                result = observe([{"type": "error", "message": message}])
                self.assert_completed(result)
                self.assertEqual(result["reconnect_notification_count"], 1)
                self.assertEqual(result["reconnect_notifications"][0]["message"], message)
                self.assertEqual(result["usage"], END[-1]["usage"])

    def test_large_decimal_retry_counts_do_not_require_integer_conversion(self):
        count = "1" + "0" * 5000
        limit = "2" + "0" * 5000
        result = observe([{"type": "error", "message": f"Reconnecting... {count}/{limit} (retrying)"}])
        self.assert_completed(result)
        self.assertTrue(result["reconnect_notifications"][0]["message_truncated"])
        result = observe([{"type": "error", "message": f"Reconnecting... {limit}/{count} (retrying)"}])
        self.assertEqual(result["status"], "MODEL_PROCESS_FAILED")

    def test_transport_reset_and_multiple_streams_are_not_attempt_counts(self):
        notices = [{"type": "error", "message": f"Reconnecting... {n}/5 (temporary failure)"}
                   for n in (1, 2, 5, 1, 2, 1)]
        result = observe(notices)
        self.assert_completed(result)
        self.assertEqual(result["reconnect_notification_count"], 6)

    def test_many_notices_truncate_display_details_not_protocol(self):
        result = observe([RETRY] * 150)
        self.assert_completed(result)
        self.assertEqual(result["reconnect_notification_count"], 150)
        self.assertEqual(len(result["reconnect_notifications"]), 100)
        self.assertTrue(result["reconnect_details_truncated"])
        self.assertEqual(result["event_count"], 154)

    def test_long_retry_reason_is_preview_truncated_not_failed(self):
        result = observe([{"type": "error", "message": "Reconnecting... 1/5 (" + "证据" * 3000 + ")"}])
        self.assert_completed(result)
        self.assertEqual(len(result["reconnect_notifications"][0]["message"]), 4096)
        self.assertTrue(result["reconnect_notifications"][0]["message_truncated"])

    def test_other_errors_and_unverified_envelopes_are_not_ignored(self):
        messages = ["401 unauthorized", "Reconnecting", "Reconnecting... 0/5 (failure)",
                    "Reconnecting... 6/5 (failure)",
                    "Reconnecting... 1/5 ()", "Reconnecting... 1/5 (failure) then failed",
                    "Reconnecting... waiting for permission"]
        for message in messages:
            with self.subTest(message=message):
                self.assertEqual(observe([{"type": "error", "message": message}])["status"], "MODEL_PROCESS_FAILED")

    def test_unknown_metadata_is_not_silently_discarded(self):
        for metadata in ({"will_retry": False}, {"willRetry": False}, {"code": "fatal"}):
            with self.subTest(metadata=metadata):
                self.assertEqual(observe([{**RETRY, **metadata}])["status"], "MODEL_PROCESS_FAILED")

    def test_retry_followed_by_fatal_error_remains_failed(self):
        result = observe([RETRY, {"type": "error", "message": "invalid credentials"}])
        self.assertEqual(result["status"], "MODEL_PROCESS_FAILED")
        self.assertEqual(result["reconnect_notification_count"], 1)

    def test_failed_turn_after_retry_cannot_be_salvaged(self):
        events = START + [RETRY, {"type": "turn.failed", "error": {"message": "retries exhausted"}}]
        self.assertEqual(observe_coding_process(raw(events), exit_code=0)["status"], "MODEL_PROCESS_FAILED")

    def test_capture_loss_timeout_and_nonzero_exit_still_take_precedence(self):
        for options, status in [({"exit_code": 1}, "MODEL_PROCESS_FAILED"),
                                ({"exit_code": None}, "UNKNOWN_SIDE_EFFECT"),
                                ({"timed_out": True}, "UNKNOWN_SIDE_EFFECT"),
                                ({"output_truncated": True}, "UNKNOWN_SIDE_EFFECT")]:
            with self.subTest(options=options):
                self.assertEqual(observe([RETRY], **options)["status"], status)

    def test_retry_without_terminal_event_is_unknown(self):
        result = observe_coding_process(raw(START + [RETRY]), exit_code=0)
        self.assertEqual(result["reason_code"], "CODEX_EVENT_STREAM_INCOMPLETE")

    def test_retry_outside_active_turn_does_not_hide_error(self):
        for events in ([RETRY] + START + END, START + END + [RETRY]):
            with self.subTest(events=events):
                self.assertEqual(observe_coding_process(raw(events), exit_code=0)["status"], "MODEL_PROCESS_FAILED")

    def test_declined_command_then_legal_alternative_is_not_unknown(self):
        result = observe([operation("item.started", status="in_progress", exit_code=None), RETRY,
                          operation("item.completed", status="declined", exit_code=None),
                          operation("item.started", identifier="alternative", status="in_progress", exit_code=None),
                          operation("item.completed", identifier="alternative", status="completed", exit_code=0)])
        self.assert_completed(result)
        self.assertEqual(result["reported_command_declines"], [{"id": "cmd", "exit_code": None, "status": "declined"}])
        self.assertEqual(result["reported_command_failures"], [])

    def test_declines_are_preserved_without_a_reconnect_too(self):
        result = observe([operation("item.completed", status="declined", exit_code=None)])
        self.assert_completed(result)
        self.assertEqual(result["reported_command_declines"][0]["status"], "declined")

    def test_child_failure_can_be_repaired_but_is_not_erased(self):
        result = observe([operation("item.started", status="in_progress"), RETRY,
                          operation("item.completed", status="failed", exit_code=1),
                          operation("item.completed", identifier="fixed", status="completed", exit_code=0)])
        self.assert_completed(result)
        self.assertEqual(result["reported_command_failures"], [{"id": "cmd", "exit_code": 1, "status": "failed"}])

    def test_missing_operation_completion_remains_unknown(self):
        for item_type in ("command_execution", "mcp_tool_call", "collab_tool_call", "web_search", "file_change"):
            with self.subTest(item_type=item_type):
                result = observe([operation("item.started", item_type=item_type, status="in_progress"), RETRY])
                self.assertEqual(result["reason_code"], "CODEX_RECONNECT_OPERATIONS_UNRESOLVED")
                self.assertFalse(result["automatic_retry_allowed"])

    def test_invalid_command_end_does_not_prove_completion(self):
        variants = [{"status": "in_progress", "exit_code": None}, {"status": "completed", "exit_code": None},
                    {"status": "completed", "exit_code": False}, {"status": "completed", "exit_code": "0"},
                    {"status": "declined", "exit_code": 0}]
        for values in variants:
            with self.subTest(values=values):
                result = observe([RETRY, operation("item.completed", **values)])
                self.assertEqual(result["reason_code"], "CODEX_RECONNECT_OPERATIONS_UNRESOLVED")

    def test_tool_completion_and_completed_only_file_change_are_supported(self):
        for item_type in ("mcp_tool_call", "collab_tool_call", "file_change"):
            for status in ("completed", "failed"):
                with self.subTest(item_type=item_type, status=status):
                    result = observe([RETRY, operation("item.completed", item_type=item_type, status=status)])
                    self.assert_completed(result)
        self.assert_completed(observe([RETRY, operation("item.completed", item_type="web_search")]))

    def test_mismatched_operation_identity_or_duplicate_start_is_unknown(self):
        variants = [[operation("item.started"), operation("item.started"), operation("item.completed", status="completed", exit_code=0)],
                    [operation("item.started"), operation("item.completed", item_type="web_search")],
                    [operation("item.completed", identifier="", status="completed", exit_code=0)]]
        for operations in variants:
            with self.subTest(operations=operations):
                self.assertEqual(observe([RETRY] + operations)["reason_code"], "CODEX_RECONNECT_OPERATIONS_UNRESOLVED")

    def test_no_reconnect_legacy_classification_is_not_broadened(self):
        self.assert_completed(observe([operation("item.started", status="in_progress")]))
        self.assert_completed(observe([operation("item.completed", status="completed")]))

    def test_contract_blocker_after_recovery_keeps_existing_boundary(self):
        blocker = {"foundry_blocker": {"failure_kind": "CONTRACT_GAP", "reason": "reviewed requirement conflicts",
                   "owner": "OWNER", "evidence": ["contract:1"], "minimum_return_path": "resolve requirement"}}
        events = START + [RETRY, {"type": "item.completed", "item": {
            "id": "answer", "type": "agent_message", "text": json.dumps(blocker)}}, END[-1]]
        result = observe_coding_process(raw(events), exit_code=0)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "CODEX_REPORTED_CONTRACT_GAP")

    def test_utf8_chunks_and_tool_text_do_not_create_retry_notifications(self):
        events = START + [RETRY, {"type": "item.completed", "item": {
            "id": "answer", "type": "agent_message", "text": "中文 Reconnecting... 1/5 (fixture)"}}, END[-1]]
        observer = CodingEventObserver()
        for byte in raw(events):
            observer.feed(bytes([byte]))
        result = observer.finish(exit_code=0)
        self.assert_completed(result)
        self.assertEqual(result["reconnect_notification_count"], 1)
        self.assertEqual(result["final_message"], events[-2]["item"]["text"])


if __name__ == "__main__":
    unittest.main()
