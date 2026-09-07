"""Real local process tests with an explicitly fake Codex/service receiver."""

import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from harness_foundry_factory.coding_process import CodingCommand, CodexCodingRunner, client_state_root
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
            self.command(reads=[client_state_root().parent]).validate()

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
