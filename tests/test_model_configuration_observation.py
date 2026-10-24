"""Local fake-receiver processes, never a real model/service qualification."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from tests.python_fixture import python_fixture_header
from unittest.mock import patch

from harness_foundry_factory.coding_process import CodingCommand, CodexCodingRunner, _dispatch_configuration
from harness_foundry_factory.local_process import LocalCommand, LocalProcessError
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.coding_events import observe_coding_process
from harness_foundry_factory.coding_process import _CodingJsonlRedactor
from harness_foundry_factory.resource_credentials import SecretRedactor


FIXTURE = r'''
import json, os, sys, tomllib
from pathlib import Path
args = sys.argv[1:]
if args == ["exec", "--help"]:
    print("--ignore-user-config --strict-config --ephemeral --json --cd stdin")
elif args == ["sandbox", "--help"]:
    print("--permission-profile --include-managed-config --cd [COMMAND]")
elif args and args[0] == "sandbox":
    assert args[args.index("--") + 1:] == ["/usr/bin/true"]
elif args and args[0] == "exec":
    options = json.loads(sys.stdin.read())
    config = {}
    for index, arg in enumerate(args):
        if index and args[index - 1] == "-c":
            key, value = arg.split("=", 1)
            config[key] = tomllib.loads("value=" + value)["value"]
    provider = config["model_provider"]
    service = config.get("model_providers." + provider, {})
    references = set(service.get("env_http_headers", {}).values())
    if "env_key" in service:
        references.add(service["env_key"])
    Path("calls").open("a").write("fixture-only\n")
    received = {"argv": args, "provider": provider, "service": service,
        "references_present": all(ref in os.environ for ref in references),
        "original_secret_forwarded": "TEST_MODEL_TOKEN" in os.environ,
        "undeclared_forwarded": "UNDECLARED_TOKEN" in os.environ,
        "private_variables": sorted(k for k in os.environ if k.startswith("FOUNDRY_MODEL_CREDENTIAL_")),
        "shell_inherit": config["shell_environment_policy.inherit"],
        "receipt_before_launch": Path(options["receipt"]).is_file()}
    Path("received.json").write_text(json.dumps(received))
    print(json.dumps({"type":"thread.started","thread_id":"LOCAL-FIXTURE"}), flush=True)
    print(json.dumps({"type":"turn.started"}), flush=True)
    if options.get("echo"):
        for ref in sorted(references):
            value = os.environ[ref]
            for ascii_only in (True, False):
                line = json.dumps({"type":"item.completed", "item":{"type":"agent_message", "id":"m", "text":value}}, ensure_ascii=ascii_only) + "\n"
                # Split token bytes across writes; host capture is the only recorder.
                raw = line.encode()
                for at in range(0, len(raw), 3):
                    sys.stdout.buffer.write(raw[at:at + 3]); sys.stdout.buffer.flush()
            sys.stderr.write(value + "\n"); sys.stderr.flush()
    if options.get("reconnect"):
        value = os.environ[service["env_key"]]
        messages = ["Reconnecting... 1/5 (echo " + value + ")",
                    "Reconnecting... 2/5 (echo " + value + ")",
                    "Reconnecting... 1/5 (echo " + value + ")",
                    "Reconnecting... waiting for network (echo " + value + ")"]
        for message in messages:
            raw = (json.dumps({"type":"error", "message":message}, ensure_ascii=False) + "\n").encode()
            for at in range(0, len(raw), 3):
                sys.stdout.buffer.write(raw[at:at + 3]); sys.stdout.buffer.flush()
    if options.get("unknown_error"):
        print(json.dumps({"type":"error", "message":"Fatal: " + os.environ[service["env_key"]]}), flush=True)
    if options.get("failed"):
        print(json.dumps({"type":"item.completed", "item":{"type":"command_execution", "id":"c", "status":"failed", "exit_code":0}}), flush=True)
    message = "fixture complete"
    if options.get("blocker_kind"):
        value = os.environ[service["env_key"]]
        kind = {"exact":value, "contains":"prefix:" + value + ":suffix", "valid":"CONTRACT_GAP"}[options["blocker_kind"]]
        message = json.dumps({"foundry_blocker":{"failure_kind":kind, "reason":"echo " + value,
            "owner":"host", "evidence":["source"], "minimum_return_path":"clarify"}})
    print(json.dumps({"type":"item.completed", "item":{"type":"agent_message", "id":"final", "text":message}}), flush=True)
    print(json.dumps({"type":"turn.failed" if options.get("failed") else "turn.completed","usage":{"input_tokens":8,"output_tokens":4}}), flush=True)
else:
    raise SystemExit(2)
'''


class ModelConfigurationObservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.cwd = self.root / "workspace"
        self.cwd.mkdir()
        self.state = self.root / "client-state"
        self.state.mkdir()
        state = patch("harness_foundry_factory.coding_process.client_state_root", return_value=self.state)
        state.start(); self.addCleanup(state.stop)
        self.executable = self.root / "fake-client"
        self.executable.write_text(python_fixture_header() + FIXTURE)
        self.executable.chmod(0o700)
        self.scope = LocalCommand.prepare(argv=[str(self.executable)], cwd=self.cwd,
            read_roots=[self.executable], write_roots=[self.cwd], timeout_seconds=10)
        self.runner = CodexCodingRunner(self.executable)
        self.journal = CommandObservation(self.root / "observation", "COMMAND-LOCAL-TEST", "CODEX")
        self.addCleanup(self.journal.close)
        self.service = {"provider":"example", "config":{"name":"Example", "base_url":"https://example.invalid/v1",
            "wire_api":"responses", "env_key":"TEST_MODEL_TOKEN", "env_http_headers":{"X-Test":"TEST_MODEL_TOKEN"}}}

    def command(self, *, dynamic=False, service=None, echo=False):
        return CodingCommand(self.scope, json.dumps({"receipt":str(self.journal.root / "model-configuration.json"), "echo":echo}),
            None if dynamic else "fixed-model", None if dynamic else "high",
            "CODEX_GLOBAL_DEFAULTS" if dynamic else "FIXED", self.service if service is None else service)

    def run_fixture(self, command, **kwargs):
        result = self.runner.run(command, before_dispatch=kwargs.pop("before_dispatch", lambda:None), observation=self.journal, **kwargs)
        self.journal.finished(result)
        self.journal.close()
        return result

    def test_client_only_declared_credentials_and_configuration_precede_launch(self):
        with patch.dict(os.environ, {"TEST_MODEL_TOKEN":"test-secret-not-real", "UNDECLARED_TOKEN":"do-not-pass"}), patch(
                "harness_foundry_factory.coding_defaults.resolve_codex_defaults", side_effect=AssertionError("fixed must not read defaults")):
            result = self.run_fixture(self.command())
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED", result)
        received = json.loads((self.cwd / "received.json").read_text())
        self.assertTrue(received["receipt_before_launch"])
        self.assertTrue(received["references_present"])
        self.assertFalse(received["original_secret_forwarded"])
        self.assertFalse(received["undeclared_forwarded"])
        self.assertEqual(received["private_variables"], ["FOUNDRY_MODEL_CREDENTIAL_1"])
        self.assertEqual(received["shell_inherit"], "none")
        self.assertEqual(received["service"]["env_key"], "FOUNDRY_MODEL_CREDENTIAL_1")
        self.assertEqual(result["model_configuration"]["model_service"], self.service)
        self.assertNotIn("test-secret-not-real", json.dumps(received))
        self.assertFalse(result["workpack_accepted"])

    def test_raw_json_escaped_and_split_credentials_never_enter_captures(self):
        secret = 'test-quote"backslash\\中文\nline-value'
        with patch.dict(os.environ, {"TEST_MODEL_TOKEN":secret}):
            result = self.run_fixture(self.command(echo=True))
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED", result)
        for file in self.journal.root.iterdir():
            body = file.read_bytes()
            for token in (secret, json.dumps(secret, ensure_ascii=True)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1]):
                self.assertNotIn(token.encode(), body, file.name)
        self.assertIn("[REDACTED]", (self.journal.root / "stdout.bin").read_text())
        self.assertIn("[REDACTED]", result["capture"]["stderr"])
        self.assertEqual(CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX")["status"], "MODEL_TURN_COMPLETED")

    def _short_credential_roundtrip(self, secret, *, failed=False):
        command = self.command(echo=True)
        options = json.loads(command.prompt)
        options["failed"] = failed
        with patch.dict(os.environ, {"TEST_MODEL_TOKEN": secret}):
            result = self.run_fixture(replace(command, prompt=json.dumps(options)))
        expected = "MODEL_PROCESS_FAILED" if failed else "MODEL_TURN_COMPLETED"
        self.assertEqual(result["status"], expected, result)
        self.assertEqual(result["usage"], {"input_tokens":8, "output_tokens":4})
        events = [json.loads(line) for line in (self.journal.root / "stdout.bin").read_text().splitlines()]
        messages = [event["item"]["text"] for event in events if event.get("item", {}).get("type") == "agent_message"]
        self.assertEqual(messages[:2], ["[REDACTED]", "[REDACTED]"])
        self.assertEqual(result["capture"]["stderr"].strip(), "[REDACTED]")
        if failed:
            self.assertEqual(result["reported_command_failures"], [{"id":"c", "exit_code":0, "status":"failed"}])
        (self.journal.root / "result.json").unlink()  # Complete capture, interrupted final-result persistence.
        before = {p.name:p.read_bytes() for p in self.journal.root.iterdir()}
        with patch("subprocess.Popen", side_effect=AssertionError("recovery cannot execute")), patch(
                "harness_foundry_factory.coding_defaults.resolve_codex_defaults", side_effect=AssertionError("no reread")):
            for _ in range(2):
                recovered = CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX")
                self.assertEqual(recovered["status"], expected)
                self.assertEqual(recovered["usage"], result["usage"])
                self.assertEqual(recovered["reported_command_failures"], result["reported_command_failures"])
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.journal.root.iterdir()})
        self.assertEqual((self.cwd / "calls").read_text().splitlines(), ["fixture-only"])

    def test_numeric_credential_preserves_usage_and_capture_only_recovery(self):
        self._short_credential_roundtrip("8")

    def test_protocol_word_credential_preserves_turn_lifecycle(self):
        self._short_credential_roundtrip("turn")

    def test_failed_credential_preserves_failed_turn_and_command(self):
        self._short_credential_roundtrip("failed", failed=True)

    def test_zero_credential_preserves_numeric_command_exit(self):
        self._short_credential_roundtrip("0", failed=True)

    def _reconnect_credential_roundtrip(self, secret, *, unknown_error=False, failed=False):
        command = self.command(echo=True)
        options = {**json.loads(command.prompt), "reconnect":True,
                   "unknown_error":unknown_error, "failed":failed}
        with patch.dict(os.environ, {"TEST_MODEL_TOKEN":secret}):
            result = self.run_fixture(replace(command, prompt=json.dumps(options)))
        expected = "MODEL_PROCESS_FAILED" if unknown_error or failed else "MODEL_TURN_COMPLETED"
        self.assertEqual(result["status"], expected, result)
        self.assertFalse(result["workpack_accepted"])
        self.assertEqual(result["reconnect_notification_count"], 4)
        messages = [row["message"] for row in result["reconnect_notifications"]]
        self.assertEqual(messages, ["Reconnecting... " + prefix + " (echo [REDACTED])"
                                   for prefix in ("1/5", "2/5", "1/5", "waiting for network")])
        self.assertEqual(result["capture"]["stderr"].strip(), "[REDACTED]")
        events = [json.loads(line) for line in (self.journal.root / "stdout.bin").read_text().splitlines()]
        self.assertEqual([row["message"] for row in events if row["type"] == "error"][:4], messages)
        if unknown_error:
            self.assertEqual([row["message"] for row in events if row["type"] == "error"][-1], "Fatal: [REDACTED]")
        for final_saved in (True, False):
            if not final_saved:
                (self.journal.root / "result.json").unlink()  # Simulate interrupted result persistence only.
            before = {p.name:p.read_bytes() for p in self.journal.root.iterdir()}
            with patch("subprocess.Popen", side_effect=AssertionError("recovery cannot execute")), patch(
                    "harness_foundry_factory.coding_defaults.resolve_codex_defaults", side_effect=AssertionError("no reread")):
                for _ in range(2):
                    recovered = CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX")
                    for key in ("status", "reason_code", "reconnect_notification_count", "reconnect_notifications",
                                "usage", "model_configuration", "reported_command_failures"):
                        self.assertEqual(recovered[key], result[key], key)
            self.assertEqual(before, {p.name:p.read_bytes() for p in self.journal.root.iterdir()})
        self.assertEqual((self.cwd / "calls").read_text().splitlines(), ["fixture-only"])

    def test_reconnect_numeric_credential_capture_and_report_recovery(self):
        self._reconnect_credential_roundtrip("1")

    def test_reconnect_network_credential_capture_and_report_recovery(self):
        self._reconnect_credential_roundtrip("network")

    def test_reconnect_prefix_credential_capture_and_report_recovery(self):
        self._reconnect_credential_roundtrip("Reconnecting")

    def test_reconnect_unicode_multiline_credential_capture_and_report_recovery(self):
        self._reconnect_credential_roundtrip('密钥"\\值\n下一行')

    def test_reconnect_unknown_error_still_fails_after_redaction_and_recovery(self):
        self._reconnect_credential_roundtrip("1", unknown_error=True)

    def test_reconnect_failed_terminal_still_fails_after_redaction_and_recovery(self):
        self._reconnect_credential_roundtrip("network", failed=True)

    def test_reconnect_boundary_spanning_credentials_mask_payload_not_protocol(self):
        cases = [("5 (private", "Reconnecting... 1/5 (private-value)", "Reconnecting... 1/5 ([REDACTED]-value)"),
                 ("private)", "Reconnecting... 1/5 (a private)", "Reconnecting... 1/5 (a [REDACTED])"),
                 ("Reconnecting... 1/5 (private)", "Reconnecting... 1/5 (private)", "Reconnecting... 1/5 ([REDACTED])"),
                 (" ", "Reconnecting... 1/5 (a b)", "Reconnecting... 1/5 (a[REDACTED]b)"),
                 ("1", "Reconnecting... 1/5 (safe detail)", "Reconnecting... 1/5 (safe detail)"),
                 ("network", "Reconnecting... waiting for network", "Reconnecting... waiting for network")]
        for secret, original, expected in cases:
            with self.subTest(secret=secret):
                events = [{"type":"thread.started","thread_id":"t"}, {"type":"turn.started"},
                          {"type":"error","message":original}, {"type":"turn.completed"}]
                raw = b"".join(json.dumps(row).encode()+b"\n" for row in events)
                stream = _CodingJsonlRedactor(SecretRedactor([secret]))
                safe = b"".join(stream.feed(raw[at:at+3]) for at in range(0,len(raw),3)) + stream.finish()
                result = observe_coding_process(safe, exit_code=0)
                self.assertEqual(result["status"], "MODEL_TURN_COMPLETED", result)
                self.assertEqual(result["reconnect_notification_count"], 1)
                self.assertEqual(result["reconnect_notifications"][0]["message"], expected)

    def test_reconnect_invalid_original_envelopes_remain_failure(self):
        cases = [{"type":"error","message":"Reconnecting... 6/5 (private)"},
                 {"type":"error","message":"Reconnecting... 0/5 (private)"},
                 {"type":"error","message":"Reconnecting... 01/5 (private)"},
                 {"type":"error","message":"Reconnecting... 1/5 (private)","code":"private"},
                 {"type":"error","message":"Fatal: private"},
                 {"type":"turn.failed","message":"Reconnecting... 1/5 (private)"}]
        for event in cases:
            with self.subTest(event=event):
                events = [{"type":"thread.started","thread_id":"t"}, {"type":"turn.started"}, event]
                if event["type"] == "error":
                    events.append({"type":"turn.completed"})
                raw = b"".join(json.dumps(row).encode()+b"\n" for row in events)
                stream = _CodingJsonlRedactor(SecretRedactor(["1","private"]))
                safe = stream.feed(raw)+stream.finish()
                self.assertNotIn(b"private", safe)
                result = observe_coding_process(safe, exit_code=0)
                self.assertEqual(result["status"], "MODEL_PROCESS_FAILED", result)
                self.assertEqual(result.get("reconnect_notification_count", 0), 0)

    def test_invalid_unknown_or_truncated_payload_is_redacted_not_completion(self):
        prefix = (b'{"type":"thread.started","thread_id":"t"}\n'
                  b'{"type":"turn.started"}\n')
        for tail in (b'{"type":"turn.unknown","text":"private-token"}\n',
                     b'{"type":"turn.completed","text":"private-to',
                     b'{"type":"turn.completed","text":"private-token"} junk\n',
                     b'{"type":"turn.completed","private-token":"value","text":"\xff"}\n'):
            with self.subTest(tail=tail):
                stream = _CodingJsonlRedactor(SecretRedactor(["private-token"]))
                original = prefix + tail
                safe = b"".join(stream.feed(original[at:at + 3]) for at in range(0, len(original), 3)) + stream.finish()
                self.assertNotIn(b"private-token", safe)
                self.assertNotIn(b"private-to", safe)
                self.assertIn(b"[REDACTED]", safe)
                self.assertEqual(observe_coding_process(safe, exit_code=0)["status"], "UNKNOWN_SIDE_EFFECT")

    def test_oversized_redacted_event_cannot_shrink_into_completion(self):
        stream = _CodingJsonlRedactor(SecretRedactor(["x" * 200]), max_event_bytes=120)
        prefix = (b'{"type":"thread.started","thread_id":"t"}\n'
                  b'{"type":"turn.started"}\n')
        original = prefix + b'{"type":"turn.completed","text":"' + b"x" * 200 + b'"}\n'
        safe = b"".join(stream.feed(original[at:at + 29]) for at in range(0, len(original), 29)) + stream.finish()
        self.assertNotIn(b"x" * 200, safe)
        self.assertEqual(observe_coding_process(safe, exit_code=0)["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(_CodingJsonlRedactor(SecretRedactor(["x"])).max_event_bytes, 8 * 1024 * 1024)

    def test_blocker_envelope_remains_a_stop_when_credential_matches_protocol(self):
        for secret in ("foundry_blocker", "CONTRACT_GAP", "{"):
            with self.subTest(secret=secret):
                report = {"foundry_blocker":{"failure_kind":"CONTRACT_GAP", "reason":"echo " + secret,
                    "owner":"host", "evidence":["source"], "minimum_return_path":"clarify"}}
                events = [{"type":"thread.started", "thread_id":"t"}, {"type":"turn.started"},
                    {"type":"item.completed", "item":{"type":"agent_message", "text":json.dumps(report)}},
                    {"type":"turn.completed", "usage":{"input_tokens":8}}]
                original = b"".join(json.dumps(event).encode() + b"\n" for event in events)
                stream = _CodingJsonlRedactor(SecretRedactor([secret]))
                safe = stream.feed(original) + stream.finish()
                result = observe_coding_process(safe, exit_code=0)
                self.assertEqual(result["status"], "VALIDATION_FAILED", result)
                self.assertEqual(result["reason_code"], "CODEX_REPORTED_CONTRACT_GAP", result)
                self.assertEqual(result["model_blocker"]["reason"], "echo [REDACTED]")

    def _blocker_credential_roundtrip(self, mode, secret):
        command = self.command()
        options = json.loads(command.prompt)
        options["blocker_kind"] = mode
        with patch.dict(os.environ, {"TEST_MODEL_TOKEN":secret}):
            result = self.run_fixture(replace(command, prompt=json.dumps(options)))
        valid = mode == "valid"
        expected = "CODEX_REPORTED_CONTRACT_GAP" if valid else "CODEX_BLOCKER_REPORT_INVALID"
        self.assertEqual(result["status"], "VALIDATION_FAILED", result)
        self.assertEqual(result["reason_code"], expected)
        self.assertFalse(result["workpack_accepted"])
        final = json.loads(result["final_message"])
        blocker = final["foundry_blocker"] if valid else final["foundry_blocker"][0]["foundry_blocker"]
        self.assertEqual(blocker["reason"], "echo [REDACTED]")
        kind = "CONTRACT_GAP" if valid else "prefix:[REDACTED]:suffix" if mode == "contains" else "[REDACTED]"
        self.assertEqual(blocker["failure_kind"], kind)
        events = [json.loads(line) for line in (self.journal.root / "stdout.bin").read_text().splitlines()]
        messages = [event["item"]["text"] for event in events if event.get("item", {}).get("type") == "agent_message"]
        self.assertEqual(messages, [result["final_message"]])
        self.assertEqual(result["capture"]["stdout"], (self.journal.root / "stdout.bin").read_text())
        if not valid:
            for file in self.journal.root.iterdir():
                self.assertNotIn(secret.encode(), file.read_bytes(), file.name)
            self.assertNotIn(secret, json.dumps(result))
        else:
            self.assertEqual(result["model_blocker"]["failure_kind"], "CONTRACT_GAP")
            self.assertEqual(result["model_blocker"]["reason"], "echo [REDACTED]")
        (self.journal.root / "result.json").unlink()  # Recover a complete capture after host persistence loss.
        before = {p.name:p.read_bytes() for p in self.journal.root.iterdir()}
        with patch("subprocess.Popen", side_effect=AssertionError("recovery cannot execute")), patch(
                "harness_foundry_factory.coding_defaults.resolve_codex_defaults", side_effect=AssertionError("no reread")):
            for _ in range(2):
                recovered = CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX")
                self.assertEqual(recovered["status"], "VALIDATION_FAILED")
                self.assertEqual(recovered["reason_code"], expected)
                self.assertEqual(recovered["final_message"], result["final_message"])
                self.assertEqual(recovered["model_configuration"], result["model_configuration"])
                self.assertEqual(recovered["usage"], result["usage"])
                if not valid:
                    self.assertNotIn(secret, json.dumps(recovered))
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.journal.root.iterdir()})
        self.assertEqual((self.cwd / "calls").read_text().splitlines(), ["fixture-only"])

    def test_invalid_blocker_kind_exact_credential_is_redacted_and_recovered(self):
        self._blocker_credential_roundtrip("exact", "fixture-invalid-secret")

    def test_invalid_blocker_kind_embedded_credential_is_redacted_and_recovered(self):
        self._blocker_credential_roundtrip("contains", "fixture-invalid-secret")

    def test_valid_blocker_kind_credential_preserves_protocol_and_recovery(self):
        self._blocker_credential_roundtrip("valid", "CONTRACT_GAP")

    def test_invalid_blocker_does_not_become_valid_after_redacting_blank_value(self):
        report = {"foundry_blocker":{"failure_kind":"CONTRACT_GAP", "reason":" ",
            "owner":"host", "evidence":["source"], "minimum_return_path":"clarify"}}
        events = [{"type":"thread.started", "thread_id":"t"}, {"type":"turn.started"},
            {"type":"item.completed", "item":{"type":"agent_message", "text":json.dumps(report)}},
            {"type":"turn.completed"}]
        original = b"".join(json.dumps(event).encode() + b"\n" for event in events)
        stream = _CodingJsonlRedactor(SecretRedactor([" "]))
        safe = stream.feed(original) + stream.finish()
        result = observe_coding_process(safe, exit_code=0)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "CODEX_BLOCKER_REPORT_INVALID")

    def test_valid_blocker_remains_valid_after_redaction_expands_text(self):
        report = {"foundry_blocker":{"failure_kind":"CONTRACT_GAP", "reason":"x " * 1500,
            "owner":"host", "evidence":["x " * 1500], "minimum_return_path":"clarify"}}
        events = [{"type":"thread.started", "thread_id":"t"}, {"type":"turn.started"},
            {"type":"item.completed", "item":{"type":"agent_message", "text":json.dumps(report)}},
            {"type":"turn.completed"}]
        original = b"".join(json.dumps(event).encode() + b"\n" for event in events)
        stream = _CodingJsonlRedactor(SecretRedactor(["x"]))
        safe = stream.feed(original) + stream.finish()
        result = observe_coding_process(safe, exit_code=0)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "CODEX_REPORTED_CONTRACT_GAP")

    def test_machine_numbers_and_matching_payload_scalars_are_distinct(self):
        events = [{"type":"thread.started", "thread_id":"t"}, {"type":"turn.started"},
            {"type":"item.completed", "item":{"type":"command_execution", "status":"completed", "exit_code":0,
                "result":{"value":8, "zero":0, "flag":False, "empty":None}}},
            {"type":"turn.completed", "usage":{"input_tokens":8, "output_tokens":0}}]
        original = b"".join(json.dumps(event).encode() + b"\n" for event in events)
        stream = _CodingJsonlRedactor(SecretRedactor(["8", "0", "false", "null"]))
        safe = stream.feed(original) + stream.finish()
        parsed = [json.loads(line) for line in safe.splitlines()]
        self.assertEqual(parsed[2]["item"]["exit_code"], 0)
        self.assertEqual(parsed[2]["item"]["result"], dict.fromkeys(("value", "zero", "flag", "empty"), "[REDACTED]"))
        self.assertEqual(parsed[3]["usage"], {"input_tokens":8, "output_tokens":0})
        self.assertEqual(observe_coding_process(safe, exit_code=0)["status"], "MODEL_TURN_COMPLETED")

    def test_complete_json_without_final_newline_remains_valid(self):
        stream = _CodingJsonlRedactor(SecretRedactor(["turn"]))
        original = (b'{"type":"thread.started","thread_id":"t"}\n'
                    b'{"type":"turn.started"}\n'
                    b'{"type":"turn.completed","usage":{"input_tokens":8}}')
        safe = stream.feed(original) + stream.finish()
        self.assertEqual(observe_coding_process(safe, exit_code=0)["status"], "MODEL_TURN_COMPLETED")

    def test_missing_credential_stops_without_model_start_or_configuration_receipt(self):
        with patch.dict(os.environ, {}, clear=True):
            result = self.run_fixture(self.command())
        self.assertEqual(result["reason_code"], "CODING_MODEL_CREDENTIAL_UNAVAILABLE")
        self.assertFalse(result["model_process_started"])
        self.assertFalse((self.cwd / "calls").exists())
        self.assertFalse((self.journal.root / "started.json").exists())
        self.assertFalse((self.journal.root / "model-configuration.json").exists())

    def test_dynamic_selection_once_before_authority_and_durable_recovery_without_reread(self):
        service = {"provider":"openai", "config":{}}
        order = []
        defaults = {"model":"selected-model", "model_reasoning_effort":"medium", "model_service":service,
                    "model_defaults_source":{"kind":"TEST-ONLY"}}
        def select(*args, **kwargs):
            self.assertFalse(kwargs["require_explicit"]); order.append("selection"); return defaults
        def current():
            order.append("authority")
            self.assertTrue((self.journal.root / "model-configuration.json").exists())
        with patch("harness_foundry_factory.coding_defaults.resolve_codex_defaults", side_effect=select) as resolver:
            result = self.run_fixture(self.command(dynamic=True, service=service), before_dispatch=current)
        resolver.assert_called_once()
        self.assertEqual(order, ["selection", "authority"])
        self.assertEqual(result["model_configuration"]["model"], "selected-model")
        (self.journal.root / "result.json").unlink()  # Simulate host loss after complete durable capture.
        before = {p.name:p.read_bytes() for p in self.journal.root.iterdir()}
        with patch("harness_foundry_factory.coding_defaults.resolve_codex_defaults", side_effect=AssertionError("recovery must not read global")), patch.object(
                self.runner, "run", side_effect=AssertionError("no replay")):
            for _ in range(2):
                recovered = CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX")
                self.assertEqual(recovered["model_configuration"], result["model_configuration"])
                self.assertEqual(recovered["status"], "MODEL_TURN_COMPLETED")
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.journal.root.iterdir()})
        self.assertEqual((self.cwd / "calls").read_text().splitlines(), ["fixture-only"])

    def test_native_null_dynamic_selection_remains_null_not_guessed(self):
        service = {"provider":"openai", "config":{}}
        defaults = {"model":None, "model_reasoning_effort":None, "model_service":service, "model_defaults_source":{}}
        with patch("harness_foundry_factory.coding_defaults.resolve_codex_defaults", return_value=defaults):
            result = self.run_fixture(self.command(dynamic=True, service=service))
        received = json.loads((self.cwd / "received.json").read_text())
        self.assertNotIn("--model", received["argv"])
        self.assertFalse(any(arg.startswith("model_reasoning_effort=") for arg in received["argv"]))
        self.assertIsNone(result["model_configuration"]["model"])

    def test_service_drift_stops_before_dispatch_and_authority_callback(self):
        defaults = {"model":"new", "model_reasoning_effort":"high", "model_service":{"provider":"openai", "config":{}}, "model_defaults_source":{}}
        with patch("harness_foundry_factory.coding_defaults.resolve_codex_defaults", return_value=defaults):
            result = self.run_fixture(self.command(dynamic=True), before_dispatch=lambda:self.fail("not dispatchable"))
        self.assertEqual(result["reason_code"], "CODING_MODEL_SERVICE_CHANGED")
        self.assertFalse(result["model_process_started"])
        self.assertFalse((self.cwd / "calls").exists())

    def test_final_revocation_preserves_selected_receipt_without_model_start(self):
        def revoked(): raise ValueError("authorization revoked")
        with patch.dict(os.environ, {"TEST_MODEL_TOKEN":"not-real"}):
            result = self.run_fixture(self.command(), before_dispatch=revoked)
        self.assertEqual(result["reason_code"], "CODING_DISPATCH_REVALIDATION_FAILED")
        self.assertFalse((self.cwd / "calls").exists())
        self.assertEqual(CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX"), result)

    def test_referenced_path_is_aliased_without_changing_process_path(self):
        service = {"provider":"example", "config":{"name":"Example", "env_key":"PATH"}}
        with patch.dict(os.environ, {"PATH":"test-token-as-path"}):
            selected, configuration, environment, redactor = _dispatch_configuration(self.command(service=service))
        self.assertEqual(environment, {"FOUNDRY_MODEL_CREDENTIAL_1":"test-token-as-path"})
        self.assertNotIn("PATH", environment)
        self.assertEqual(configuration["model_service"], service)
        self.assertEqual(selected.model_service["config"]["env_key"], "FOUNDRY_MODEL_CREDENTIAL_1")

    def test_old_dynamic_command_without_service_must_reprepare(self):
        with self.assertRaisesRegex(LocalProcessError, "bound model service"):
            replace(self.command(dynamic=True), model_service=None).validate()

    def test_configuration_is_bound_once_and_cannot_be_replaced(self):
        config = {"model":"one"}
        self.journal.model_configuration(config)
        self.journal.model_configuration(config)
        with self.assertRaisesRegex(ValueError, "already bound"):
            self.journal.model_configuration({"model":"two"})

    def test_wrong_command_receipt_or_missing_receipt_is_not_recovered(self):
        self.journal.model_configuration({"model":"one"})
        self.journal.finished({"model_configuration":{"model":"one"}, "status":"TEST-ONLY"})
        path = self.journal.root / "model-configuration.json"
        original = json.loads(path.read_text())
        altered = deepcopy(original); altered["binding"]["command_id"] = "OTHER"
        path.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, "binding"):
            CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX")
        path.unlink()
        with self.assertRaisesRegex(ValueError, "no bound receipt"):
            CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX")

    def test_result_or_nested_capture_must_match_original_configuration(self):
        self.journal.model_configuration({"model":"one"})
        for result in ({"model_configuration":{"model":"two"}},
                       {"model_configuration":{"model":"one"}, "capture":{"model_configuration":{"model":"two"}}},
                       {"model_configuration":{"model":"one"}, "capture":{}}):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.journal.finished(result)

    def test_legacy_result_without_configuration_remains_recoverable(self):
        result = {"status":"MODEL_TURN_COMPLETED", "workpack_accepted":False}
        self.journal.finished(result)
        self.assertEqual(CommandObservation.recover(self.journal.root, "COMMAND-LOCAL-TEST", "CODEX"), result)
        self.assertFalse((self.journal.root / "model-configuration.json").exists())


if __name__ == "__main__":
    unittest.main()
