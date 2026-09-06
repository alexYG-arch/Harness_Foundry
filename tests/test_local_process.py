"""Receiver contract tests and opt-in real, offline Codex sandbox integration."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

from harness_foundry_factory.local_process import (
    CodexSandboxRunner, LocalCommand, LocalProcessError, _toml_inline,
)
from harness_foundry_factory.control_kernel import (
    GenericTransitionEngine, InjectedKernelCrash, prepare_parent_authorization_challenge,
)
from harness_foundry_factory.store import ControlEventStore
from tests import test_runtime_advance_cli as support


class LocalProcessContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / 'job with "quote" and 中文'
        self.work.mkdir()
        self.command = LocalCommand.prepare(argv=["/usr/bin/true"], cwd=self.work,
                                            read_roots=["/usr/bin/true"], write_roots=[self.work])
        self.runner = CodexSandboxRunner("/usr/bin/true")  # Never a real sandbox: failure-path fixture.

    def test_profile_roundtrips_paths_and_has_no_implicit_writable_temp(self):
        profile = self.command.permission_profile()
        parsed = tomllib.loads("profile=" + _toml_inline(profile))["profile"]
        self.assertEqual(parsed, profile)
        self.assertEqual(profile["network"], {"enabled": False})
        self.assertEqual({key for key, value in profile["filesystem"].items() if value == "write"}, {str(self.work)})
        self.assertEqual(profile["filesystem"][str(self.work / ".git")], "read")
        self.assertNotIn(":root", profile["filesystem"])

    def test_invalid_scope_timeout_and_argv_fail_without_process(self):
        baseline = dict(argv=["/usr/bin/true"], cwd=self.work,
                        read_roots=["/usr/bin/true"], write_roots=[self.work])
        mutations = [dict(argv=["true"]), dict(argv=["/usr/bin/true", "\0"]),
                     dict(write_roots=[]), dict(read_roots=[]),
                     dict(timeout_seconds=True), dict(timeout_seconds=float("nan")),
                     dict(timeout_seconds=float("inf")), dict(timeout_seconds=0)]
        with patch("harness_foundry_factory.local_process.subprocess.Popen") as popen:
            for mutation in mutations:
                with self.subTest(mutation=mutation), self.assertRaises(LocalProcessError):
                    LocalCommand.prepare(**(baseline | mutation))
            popen.assert_not_called()

    def test_missing_or_old_cli_interface_never_dispatches_workload(self):
        # Real /usr/bin/true cannot act as a sandbox; a zero help exit is not readiness.
        result = self.runner.run(self.command)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "SANDBOX_INTERFACE_UNAVAILABLE")
        self.assertIs(result["workload_started"], False)

    def test_sandbox_application_failure_never_falls_back(self):
        output = dict(exit_code=0, timed_out=False, stdout="[COMMAND] --permission-profile --include-managed-config --cd",
                      stderr="", output_truncated=False)
        failed = output | dict(exit_code=71, stdout="", stderr="sandbox_apply: Operation not permitted")
        with patch.object(self.runner, "_capture", side_effect=[output, failed]) as capture:
            result = self.runner.run(self.command)
        self.assertEqual(capture.call_count, 2)
        self.assertEqual(result["reason_code"], "SANDBOX_UNAVAILABLE")
        self.assertIs(result["workload_started"], False)
        invocation = capture.call_args.args[0]
        self.assertIn("--include-managed-config", invocation)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", invocation)

    def test_prepared_path_drift_is_checked_again_before_dispatch(self):
        self.work.rmdir()
        self.work.symlink_to(self.root, target_is_directory=True)
        with patch.object(self.runner, "_capture") as capture, self.assertRaises(LocalProcessError):
            self.runner.run(self.command)
        capture.assert_not_called()

    def test_python_venv_argv_is_not_rewritten_to_base_interpreter(self):
        command = LocalCommand.prepare(argv=[sys.executable, "-c", "pass"], cwd=self.work,
                                       read_roots=[sys.prefix, sys.base_prefix], write_roots=[self.work])
        self.assertEqual(command.argv[0], sys.executable)

    def test_api_keys_and_python_hooks_are_not_forwarded(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "TEST-NOT-A-KEY", "PYTHONPATH": "/test-hook",
                                     "HTTPS_PROXY": "http://test.invalid"}):
            self.assertEqual(self.runner._environment(), {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})


@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"),
                     "real Codex sandbox integration requires an explicit local opt-in")
class RealCodexSandboxTests(unittest.TestCase):
    """Temporary offline child commands only; no model, Workpack or Harness."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / "job"
        self.work.mkdir()
        self.input = self.root / "input"
        self.input.mkdir()
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.runner = CodexSandboxRunner(os.environ["HFFACTORY_TEST_CODEX_SANDBOX"])
        # Interpreter installations can have an additional loader/link tree.
        # Keep that host-local dependency binding explicit, not a broad default
        # read grant or a Homebrew-specific path in the production receiver.
        self.runtime_reads = [sys.prefix, sys.base_prefix, Path(sys._base_executable).parent,
                              *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]

    def command(self, code, *, timeout=10):
        return LocalCommand.prepare(argv=[sys.executable, "-B", "-c", code], cwd=self.work,
                                    read_roots=[*self.runtime_reads, self.input],
                                    write_roots=[self.work], timeout_seconds=timeout)

    def test_real_reads_writes_and_venv_identity(self):
        (self.input / "value.txt").write_text("INPUT", encoding="utf-8")
        code = ("from pathlib import Path; import sys; "
                f"Path('output.txt').write_text(Path({str(self.input / 'value.txt')!r}).read_text()); "
                "print(sys.prefix)")
        result = self.runner.run(self.command(code))
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual((self.work / "output.txt").read_text(), "INPUT")
        self.assertEqual(Path(result["stdout"].strip()).resolve(), Path(sys.prefix).resolve())

    def test_os_denies_sibling_reads_input_writes_and_sibling_writes(self):
        outside = self.outside / "value.txt"
        outside.write_text("PRIVATE")
        inp = self.input / "value.txt"
        inp.write_text("READ-ONLY")
        for code in (f"open({str(outside)!r}).read()",
                     f"open({str(inp)!r}, 'w').write('CHANGED')",
                     f"open({str(self.outside / 'new.txt')!r}, 'w').write('CHANGED')"):
            with self.subTest(code=code):
                result = self.runner.run(self.command(code))
                self.assertEqual(result["status"], "VALIDATION_FAILED", result)
                self.assertEqual(result["reason_code"], "LOCAL_PROCESS_NONZERO_EXIT", result)
                self.assertIn("PermissionError", result["stderr"])
        self.assertEqual(outside.read_text(), "PRIVATE")
        self.assertEqual(inp.read_text(), "READ-ONLY")
        self.assertFalse((self.outside / "new.txt").exists())

    def test_os_denies_network_binding_without_contacting_any_service(self):
        result = self.runner.run(self.command("import socket; s=socket.socket(); s.bind(('127.0.0.1', 0))"))
        self.assertEqual(result["status"], "VALIDATION_FAILED", result)
        self.assertIn("PermissionError", result["stderr"])

    def test_readonly_job_and_repository_metadata_remain_readonly(self):
        metadata = self.work / ".git"
        metadata.mkdir()
        (metadata / "config").write_text("ORIGINAL")
        command = self.command("open('.git/config', 'w').write('CHANGED')")
        result = self.runner.run(command)
        self.assertEqual(result["reason_code"], "LOCAL_PROCESS_NONZERO_EXIT", result)
        self.assertIn("PermissionError", result["stderr"])
        readonly = LocalCommand.prepare(argv=[sys.executable, "-B", "-c", "open('new', 'w').write('X')"],
                                        cwd=self.work, read_roots=[*self.runtime_reads, self.work], write_roots=[])
        result = self.runner.run(readonly)
        self.assertEqual(result["reason_code"], "LOCAL_PROCESS_NONZERO_EXIT", result)
        self.assertIn("PermissionError", result["stderr"])
        self.assertFalse((self.work / "new").exists())
        self.assertEqual((metadata / "config").read_text(), "ORIGINAL")

    def test_timeout_kills_child_group_and_preserves_partial_effect_state(self):
        code = ("import subprocess, sys, time; from pathlib import Path; "
                "Path('started').write_text('yes'); "
                "subprocess.Popen([sys.executable, '-c', "
                "\"import time; from pathlib import Path; time.sleep(2); Path('late').write_text('leak')\"]); "
                "time.sleep(10)")
        result = self.runner.run(self.command(code, timeout=0.7))
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT", result)
        self.assertTrue(result["timed_out"])
        self.assertTrue((self.work / "started").exists())
        time.sleep(2)
        self.assertFalse((self.work / "late").exists())

    def test_real_output_is_bounded_and_exit_status_is_not_inferred_from_text(self):
        runner = CodexSandboxRunner(self.runner.executable, output_limit_bytes=1024)
        result = runner.run(self.command("import sys; print('PASS' * 10000); sys.exit(7)"))
        self.assertEqual(result["status"], "VALIDATION_FAILED", result)
        self.assertEqual(result["exit_code"], 7)
        self.assertTrue(result["output_truncated"])
        self.assertLessEqual(len(result["stdout"].encode()), 1024)

    def test_normal_exit_also_cleans_up_its_background_process_group(self):
        code = ("import subprocess, sys; "
                "subprocess.Popen([sys.executable, '-c', "
                "\"import time; from pathlib import Path; time.sleep(2); Path('late').write_text('leak')\"])")
        result = self.runner.run(self.command(code))
        self.assertEqual(result["status"], "PASS", result)
        time.sleep(2)
        self.assertFalse((self.work / "late").exists())

    def test_durable_kernel_recovers_real_sandbox_outcome_without_reexecution(self):
        database = self.root / "control.sqlite3"
        program = "PROGRAM-REAL-SANDBOX-TEST"
        store = ControlEventStore(database)
        parent = support.parent(program)
        transition = support.transition("T-LOCAL", "STATE")
        transition["command_contract"]["delivery_mode"] = "DURABLE_SINGLE_ATTEMPT"
        transition["result_schema"]["properties"]["process_result"] = {"type": "object"}
        command = self.command("with open('effects', 'a') as f: f.write('APPLIED\\n')")
        observed = []

        def adapter(context):
            # The fixture owns and maps this one temporary Job; not a public
            # request-to-local-path binding or target execution authorization.
            self.assertTrue(any(e["event_type"] == "TRANSITION_ATTEMPT_STARTED"
                                for e in store.list_events(program)))
            result = self.runner.run(command)
            observed.append(result)
            return {"status": result["status"], "reason_code": result["reason_code"],
                    "artifact_id": "TEST-REAL-LOCAL-PROCESS", "process_result": result}

        engine = GenericTransitionEngine(store, {"STATE": adapter})
        challenge = prepare_parent_authorization_challenge(parent, expected_bindings=support.bindings())
        engine.register_approved_parent_authorization(parent, challenge, {
            "decision": "APPROVE", "challenge_sha256": challenge["challenge_sha256"],
            "approved_by": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST", "turn_id": "TEST"},
            "approved_at": support.NOW}, created_at=support.NOW)
        with self.assertRaises(InjectedKernelCrash):
            engine.execute_transition(program, parent["authorization_id"], transition, {"approved": True},
                                      created_at=support.NOW, inject_crash_after_command=True)
        self.assertEqual(observed[0]["exit_code"], 0, observed)
        restarted = GenericTransitionEngine(ControlEventStore(database), {})
        result = restarted.execute_transition(program, parent["authorization_id"], transition,
                                              {"approved": True}, created_at=support.NOW, resume=True)
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(result["result"]["process_result"], observed[0])
        self.assertEqual((self.work / "effects").read_text(), "APPLIED\n")
        self.assertEqual(len(observed), 1)
        self.assertEqual(store.verify_stream(program)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
