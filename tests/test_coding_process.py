"""Real local process tests with an explicitly fake Codex/service receiver."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

from harness_foundry_factory.coding_process import (
    CodingCommand, CodexCodingRunner, client_state_root, instruction_read_preflight,
)
from harness_foundry_factory.local_process import LocalCommand, LocalProcessError


def fixture_executable(root):
    path = root / "test-only-codex"
    path.write_text("#!" + sys.executable + "\n" + (Path(__file__).parent / "fixtures/coding_process_fixture.py").read_text())
    path.chmod(0o700)
    return path


class CodingProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        # A fixture must not inherit the operator's global instructions.
        self.client_home = self.root / "client-state"
        self.client_home.mkdir()
        self.state_patch = patch("harness_foundry_factory.coding_process.client_state_root", return_value=self.client_home)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.executable = fixture_executable(self.root)
        self.runner = CodexCodingRunner(self.executable)

    def command(self, prompt="TEST ONLY", timeout=10, reads=()):
        scope = LocalCommand.prepare(argv=[str(self.executable)], cwd=self.cwd,
            read_roots=[self.executable, *reads], write_roots=[self.cwd], timeout_seconds=timeout)
        return CodingCommand(scope, prompt)

    def test_real_process_receives_large_unicode_stdin_without_argv_or_secret_injection(self):
        prompt = "测试" * 200000
        rechecks = []
        with patch.dict(os.environ, {"OPENAI_API_KEY": "TEST-NOT-A-KEY", "CODEX_API_KEY": "TEST-NOT-A-KEY"}):
            result = self.runner.run(self.command(prompt), before_dispatch=lambda: rechecks.append("CURRENT"))
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED", result)
        received = json.loads((self.cwd / "fixture-input.json").read_text())
        self.assertEqual(received["prompt"], prompt)
        self.assertNotIn(prompt, received["argv"])
        self.assertFalse(received["forwarded_secret"])
        self.assertEqual(rechecks, ["CURRENT"])
        self.assertFalse(result["workpack_accepted"])
        self.assertEqual(result["client_network"], "CODEX_SERVICE_TRAFFIC")
        self.assertEqual(result["local_command_network"], "DENY")

    def test_argv_keeps_local_tool_scope_and_disables_other_surfaces(self):
        argv = self.command().argv()
        config = dict(arg.split("=", 1) for index, arg in enumerate(argv) if index and argv[index - 1] == "-c")
        name = tomllib.loads("name=" + config["default_permissions"])["name"]
        profile = tomllib.loads("p=" + config["permissions." + name])["p"]
        self.assertEqual(profile["network"], {"enabled": False})
        self.assertEqual(profile["filesystem"][str(self.cwd)], "write")
        self.assertEqual(config["features.apps"], "false")
        self.assertEqual(config["features.plugins"], "false")
        self.assertEqual(config["features.hooks"], "false")
        self.assertNotIn("--sandbox", argv)
        self.assertNotIn("--ignore-rules", argv)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)

    def test_valid_large_stream_and_diagnostic_clipping_preserve_terminal(self):
        for mode in ("large_unicode", "large_stream", "large_stderr"):
            with self.subTest(mode=mode):
                (self.cwd / "fixture-mode").write_text(mode)
                result = self.runner.run(self.command(), before_dispatch=lambda: None)
                self.assertEqual(result["status"], "MODEL_TURN_COMPLETED", result["reason_code"])
                self.assertTrue(result["capture"]["output_truncated"])
                self.assertFalse(result["workpack_accepted"])
                self.assertEqual(result["usage"]["output_tokens"], 1)
                self.assertLessEqual(len(result["capture"]["stdout"].encode()), 65536)

    def test_exit_zero_without_terminal_stays_unknown(self):
        (self.cwd / "fixture-mode").write_text("missing_terminal")
        result = self.runner.run(self.command(), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertFalse(result["workpack_accepted"])

    def test_running_model_fixture_cancel_is_unknown_not_business_failure(self):
        (self.cwd / "fixture-mode").write_text("timeout")
        started = time.monotonic()
        result = self.runner.run(self.command(), before_dispatch=lambda: None,
            cancellation_reason=lambda: "BUILD_AUTHORIZATION_REVOKED"
                if (self.cwd / "fixture-calls.txt").exists() else None)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(result["reason_code"], "CODING_PROCESS_CANCELLED")
        self.assertFalse(result["workpack_accepted"])
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertFalse(result["capture"]["timed_out"])

    def test_profile_conflicting_project_config_is_not_ignored_or_rewritten(self):
        path = self.cwd / ".codex/config.toml"
        path.parent.mkdir()
        path.write_text('sandbox_mode="danger-full-access"\n')
        with self.assertRaises(LocalProcessError):
            self.runner.run(self.command(), before_dispatch=lambda: None)
        self.assertEqual(path.read_text(), 'sandbox_mode="danger-full-access"\n')
        self.assertFalse((self.cwd / "fixture-calls.txt").exists())

    def test_scope_cannot_expose_client_authentication_to_model_tools(self):
        with self.assertRaises(LocalProcessError):
            self.command(reads=[self.client_home.parent]).validate()

    def test_revocation_after_probes_prevents_model_dispatch(self):
        def changed():
            raise ValueError("TEST revoked during probes")
        result = self.runner.run(self.command(), before_dispatch=changed)
        self.assertEqual(result["reason_code"], "CODING_DISPATCH_REVALIDATION_FAILED")
        self.assertIs(result["model_process_started"], False)
        self.assertFalse((self.cwd / "fixture-calls.txt").exists())

    def test_incomplete_or_failed_process_is_not_a_completed_turn_or_retry_instruction(self):
        for mode, expected in (("failed", "MODEL_PROCESS_FAILED"), ("malformed", "UNKNOWN_SIDE_EFFECT"),
                               ("timeout", "UNKNOWN_SIDE_EFFECT"), ("truncated", "UNKNOWN_SIDE_EFFECT")):
            with self.subTest(mode=mode):
                (self.cwd / "fixture-mode").write_text(mode)
                runner = CodexCodingRunner(self.executable, output_limit_bytes=1024 if mode == "truncated" else 65536)
                result = runner.run(self.command(timeout=1 if mode == "timeout" else 10), before_dispatch=lambda: None)
                self.assertEqual(result["status"], expected, result)
                self.assertFalse(result["workpack_accepted"])
                self.assertFalse(result["automatic_retry_allowed"])

    def test_non_receiver_cannot_be_promoted_from_exit_zero_help(self):
        scope = LocalCommand.prepare(argv=["/usr/bin/true"], cwd=self.cwd,
                                     read_roots=["/usr/bin/true"], write_roots=[self.cwd])
        result = CodexCodingRunner("/usr/bin/true").run(CodingCommand(scope, "TEST"), before_dispatch=lambda: None)
        self.assertEqual(result["reason_code"], "CODING_CLI_INTERFACE_UNAVAILABLE")
        self.assertFalse(result["model_process_started"])

    def test_missing_ancestor_instruction_read_blocks_before_any_process(self):
        (self.root / ".git").mkdir()
        instructions = self.root / "AGENTS.md"
        instructions.write_text("Preserve the test instructions.\n")
        with patch.object(self.runner, "_capture") as capture:
            result = self.runner.run(self.command(), before_dispatch=lambda: None)
        self.assertEqual(result["reason_code"], "CODING_INSTRUCTION_READS_REQUIRED")
        self.assertEqual(result["instruction_preflight"]["missing_read_paths"], [str(instructions)])
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertFalse(result["model_process_started"])
        capture.assert_not_called()
        self.assertEqual(instructions.read_text(), "Preserve the test instructions.\n")

    def test_exact_instruction_file_reads_do_not_expose_auth_directory(self):
        instructions = self.client_home / "AGENTS.md"
        instructions.write_text("")  # Empty files must still be readable during discovery.
        auth = self.client_home / "auth.json"
        auth.write_text("TEST ONLY NOT A CREDENTIAL")
        command = self.command(reads=[instructions])
        command.validate()
        result = self.runner.run(command, before_dispatch=lambda: None)
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED", result)
        profile = command.scope.permission_profile()["filesystem"]
        self.assertEqual(profile[str(instructions)], "read")
        self.assertNotIn(str(self.client_home), profile)
        self.assertNotIn(str(auth), profile)
        with self.assertRaises(LocalProcessError):
            self.command(reads=[auth]).validate()
        instructions.unlink()
        instructions.symlink_to(auth)
        with self.assertRaises(LocalProcessError):
            self.command(reads=[instructions]).validate()

    def test_instruction_discovery_respects_root_override_and_missing_target(self):
        (self.root / ".git").mkdir()
        root_doc = self.root / "AGENTS.md"
        root_doc.write_text("root")
        override = self.cwd / "AGENTS.override.md"
        override.write_text("local override")
        (self.cwd / "AGENTS.md").write_text("shadowed")
        result = instruction_read_preflight(self.cwd / "not-created", [root_doc, self.cwd])
        self.assertEqual(result["instruction_files"], [str(root_doc), str(override)])
        self.assertEqual(result["missing_read_paths"], [])
        self.assertFalse((self.cwd / "not-created").exists())

    def test_instruction_drift_after_probe_stops_before_dispatch(self):
        def add_instruction(*args, **kwargs):
            (self.client_home / "AGENTS.md").write_text("new global guidance")
            return {"status": "PASS"}
        with patch("harness_foundry_factory.coding_process.CodexSandboxRunner.run", side_effect=add_instruction):
            result = self.runner.run(self.command(), before_dispatch=lambda: None)
        self.assertEqual(result["reason_code"], "CODING_INSTRUCTION_READS_REQUIRED")
        self.assertFalse((self.cwd / "fixture-calls.txt").exists())
