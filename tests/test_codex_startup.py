"""Startup repair fixtures: local engineering only, no model or business."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory import local_process
from harness_foundry_factory.coding_process import CodingCommand, CodexCodingRunner
from harness_foundry_factory.models import RequestValidationError
from harness_foundry_factory.build_runtime import NativeBuildRunner, prepare_build_scope
from harness_foundry_factory.coding_process import validate_coding_paths, classify_coding_capture
from harness_foundry_factory.coding_events import CodingEventObserver
from harness_foundry_factory.process_observation import CommandObservation
from tests.test_coding_process import fixture_executable
from tests.test_build_runtime import BuildRuntimeTests


class ReceiverBindingTests(unittest.TestCase):
    def test_binary_alias_binding_and_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            alias = root / "codex"
            alias.symlink_to("/usr/bin/true")
            binding = local_process.bind_codex_receiver(str(alias))
            self.assertEqual(binding["declared_executable"], str(alias))
            self.assertEqual(binding["executable"], str(Path("/usr/bin/true").resolve()))
            local_process.validate_codex_receiver(binding)
            alias.unlink()
            alias.symlink_to("/usr/bin/false")
            with self.assertRaisesRegex(local_process.LocalProcessError, "CODEX_RECEIVER_CHANGED"):
                local_process.validate_codex_receiver(binding)

    def test_parent_alias_and_script_wrapper_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "安装 目录").symlink_to(Path("/usr/bin"), target_is_directory=True)
            binary = local_process.bind_codex_receiver(root / "安装 目录/true")
            self.assertEqual(binary["executable"], str(Path("/usr/bin/true").resolve()))
            wrapper = root / "wrapper"
            wrapper.write_text("#!/bin/sh\nprintf '%s' \"$0\"\n")
            wrapper.chmod(0o700)
            alias = root / "wrapper-alias"
            alias.symlink_to(wrapper)
            binding = local_process.bind_codex_receiver(alias)
            self.assertEqual(binding["executable"], str(alias))
            self.assertEqual(local_process.CodexSandboxRunner(alias).executable, alias)
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            with self.assertRaisesRegex(local_process.LocalProcessError, "CODEX_RECEIVER_CHANGED"):
                local_process.validate_codex_receiver(binding)

    def test_ordinary_venv_entry_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            command = local_process.LocalCommand.prepare(argv=[sys.executable, "-c", "pass"],
                cwd=directory, read_roots=[sys.prefix, sys.base_prefix], write_roots=[directory])
            self.assertEqual(command.argv[0], sys.executable)

    def test_invalid_receiver_remains_a_local_validation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "not-executable"; plain.write_text("text")
            for entry in (root, plain):
                with self.subTest(entry=entry), self.assertRaises(local_process.LocalProcessError):
                    local_process.CodexSandboxRunner(entry)

    def test_exact_instruction_read_and_missing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"; state.mkdir()
            instruction = state / "AGENTS.md"; instruction.write_text("")
            auth = state / "auth.json"; auth.write_text("{}")
            with patch("harness_foundry_factory.coding_process.client_state_root", return_value=state):
                validate_coding_paths(root / "future", [instruction], [root / "future"])
                instruction.unlink(); instruction.symlink_to(auth)
                with self.assertRaisesRegex(local_process.LocalProcessError, "authentication/state"):
                    validate_coding_paths(root / "future", [instruction], [root / "future"])
            self.assertFalse((root / "future").exists())


class DispatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.work = self.root / "work"; self.work.mkdir()
        self.state = self.root / "state"; self.state.mkdir()
        state = patch("harness_foundry_factory.coding_process.client_state_root", return_value=self.state)
        state.start(); self.addCleanup(state.stop)
        self.executable = fixture_executable(self.root)
        self.binding = local_process.bind_codex_receiver(self.executable)
        self.command = CodingCommand(local_process.LocalCommand.prepare(
            argv=[str(self.executable)], cwd=self.work,
            read_roots=[self.executable], write_roots=[self.work], timeout_seconds=10), "TEST")

    def test_real_fixture_bound_probe_dispatch_and_capture_only_recovery(self):
        observation = CommandObservation(self.root / "observation", "CMD", "CODEX")
        try:
            result = CodexCodingRunner(self.executable).run(self.command, before_dispatch=lambda: None,
                receiver_binding=self.binding, observation=observation)
        finally:
            observation.close()
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED", result)
        self.assertEqual(result["model_configuration"]["codex_receiver_binding"], self.binding)
        self.assertEqual(result["capture"]["startup_probe"]["argv"], [str(self.executable), "exec", "--help"])
        self.assertFalse(result["capture"]["startup_probe"]["session_readiness_verified"])
        # Only capture exists: no result.json and no current environment needed.
        before = (self.work / "fixture-calls.txt").read_bytes()
        self.executable.unlink()
        with patch.object(CodexCodingRunner, "_capture", side_effect=AssertionError("no replay")):
            for _ in range(2):
                recovered = CommandObservation.recover(self.root / "observation", "CMD", "CODEX")
                self.assertEqual(recovered["model_configuration"], result["model_configuration"])
                self.assertEqual(recovered["status"], result["status"])
        self.assertEqual((self.work / "fixture-calls.txt").read_bytes(), before)

    def test_receiver_drift_refuses_before_process(self):
        self.executable.write_text(self.executable.read_text() + "\n# changed\n")
        with patch.object(CodexCodingRunner, "_capture") as capture:
            with self.assertRaisesRegex(local_process.LocalProcessError, "CODEX_RECEIVER_CHANGED"):
                CodexCodingRunner(self.executable).run(self.command, before_dispatch=lambda: None,
                    receiver_binding=self.binding)
            capture.assert_not_called()

    def test_diagnostic_reuse_never_reuses_authority_and_changed_scope_reprobes(self):
        cache = {}
        runner = CodexCodingRunner(self.executable)
        with patch.object(local_process.CodexSandboxRunner, "run", return_value={"status": "PASS"}) as probe:
            runner.run(self.command, before_dispatch=lambda: None, receiver_binding=self.binding, startup_evidence=cache)
            result = runner.run(self.command, before_dispatch=lambda: None, receiver_binding=self.binding, startup_evidence=cache)
            self.assertTrue(result["capture"]["startup_probe"]["reused"])
            self.assertEqual(probe.call_count, 1)
            calls = (self.work / "fixture-calls.txt").read_bytes()
            def revoked():
                raise ValueError("REVOKED")
            result = runner.run(self.command, before_dispatch=revoked, receiver_binding=self.binding, startup_evidence=cache)
            self.assertFalse(result["model_process_started"])
            self.assertEqual((self.work / "fixture-calls.txt").read_bytes(), calls)
            from dataclasses import replace
            other = self.root / "read-only"; other.mkdir()
            changed = replace(self.command, scope=local_process.LocalCommand.prepare(
                argv=[str(self.executable)], cwd=self.work, read_roots=[self.executable, other],
                write_roots=[self.work], timeout_seconds=10))
            runner.run(changed, before_dispatch=lambda: None, receiver_binding=self.binding, startup_evidence=cache)
            self.assertEqual(probe.call_count, 2)

    def test_actual_entry_probe_failure_does_not_dispatch_model(self):
        output = {"status": "VALIDATION_FAILED", "exit_code": 71, "timed_out": False,
                  "stderr": "sandbox-exec: execvp() denied", "stdout": ""}
        with patch.object(local_process.CodexSandboxRunner, "run", return_value=output) as probe:
            result = CodexCodingRunner(self.executable).run(self.command, before_dispatch=lambda: None,
                receiver_binding=self.binding)
        self.assertFalse(result["model_process_started"])
        self.assertEqual(probe.call_args.args[0].argv, (str(self.executable), "exec", "--help"))
        self.assertEqual(probe.call_args.args[0].permission_profile(), self.command.scope.permission_profile())
        self.assertFalse((self.work / "fixture-calls.txt").exists())

    def test_probe_consumes_same_deadline(self):
        clock = [0.]
        runner = CodexCodingRunner(self.executable)
        help_result = {"exit_code": 0, "timed_out": False,
                       "stdout": "--ignore-user-config --strict-config --ephemeral --json --cd stdin", "stderr": ""}
        def delayed(*args, **kwargs):
            clock[0] = 11.
            return help_result
        with patch("harness_foundry_factory.coding_process.time.monotonic", side_effect=lambda: clock[0]), \
                patch.object(runner, "_capture", side_effect=delayed) as capture:
            result = runner.run(self.command, before_dispatch=lambda: None, receiver_binding=self.binding)
        self.assertEqual(result["reason_code"], "CODING_TIMEOUT_BEFORE_DISPATCH")
        self.assertFalse(result["model_process_started"])
        self.assertEqual(capture.call_count, 1)
        self.assertEqual(capture.call_args.args[2], 10)

    def test_native_sync_rejection_is_durable_without_fabricated_capture(self):
        invocation = {"scope": {"codex_executable": str(self.executable), "model": "TEST"},
            "executor": "CODEX", "argv": [str(self.executable)], "cwd": str(self.work),
            "read_roots": [str(self.executable), str(self.state)], "write_roots": [str(self.work)],
            "timeout_seconds": 10, "command_id": "CMD", "observation_root": str(self.root / "obs"),
            "prompt": "TEST", "phase": "IMPLEMENTATION", "codex_receiver_binding": self.binding}
        with patch("harness_foundry_factory.local_process.subprocess.Popen") as popen:
            result = NativeBuildRunner()(invocation, lambda: None)
            popen.assert_not_called()
        self.assertEqual(result["startup_phase"], "SYNCHRONOUS_VALIDATION")
        self.assertFalse(result["model_process_started"])
        self.assertFalse((self.root / "obs/capture.json").exists())
        for _ in range(2):
            self.assertEqual(CommandObservation.recover(self.root / "obs", "CMD", "CODEX"), result)

    def test_sync_rejection_diagnostic_redacts_declared_credentials(self):
        token = "odd token / 中文"
        self.command.scope.cwd.joinpath(".codex").mkdir()
        self.command.scope.cwd.joinpath(".codex/config.toml").write_text("a=1")
        invocation = {"scope": {"codex_executable": str(self.executable), "model": "TEST",
            "model_service": {"provider": "example", "config": {"env_key": "TEST_STARTUP_TOKEN", "base_url": "https://example.test"}}},
            "executor": "CODEX", "argv": [str(self.executable)], "cwd": str(self.work),
            "read_roots": [str(self.executable)], "write_roots": [str(self.work)],
            "timeout_seconds": 10, "prompt": "TEST", "phase": "IMPLEMENTATION"}
        with patch.dict(os.environ, {"TEST_STARTUP_TOKEN": token}), \
                patch("harness_foundry_factory.coding_process.validate_coding_paths",
                      side_effect=local_process.LocalProcessError("failed " + token)):
            result = NativeBuildRunner()(invocation, lambda: None)
        self.assertNotIn(token, json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["startup_phase"], "SYNCHRONOUS_VALIDATION")

    def test_incomplete_observation_is_not_no_start(self):
        observation = CommandObservation(self.root / "obs", "CMD", "CODEX")
        observation.close()
        self.assertIsNone(CommandObservation.recover(self.root / "obs", "CMD", "CODEX"))

    def test_helper_diagnostic_does_not_change_failure_or_infer_zero_cost(self):
        stderr = "fs sandbox helper failed with status exit status: 71: sandbox-exec: execvp() denied"
        capture = {"exit_code": 1, "timed_out": False, "stdout": "", "stderr": stderr}
        result = classify_coding_capture(capture, CodingEventObserver())
        self.assertEqual(result["startup_phase"], "SESSION_HELPER_REJECTED")
        self.assertTrue(result["parent_process_started"])
        self.assertIsNone(result["model_process_started"])
        self.assertEqual(result["status"], "MODEL_PROCESS_FAILED")
        for change in ({"exit_code": 0}, {"timed_out": True}, {"capture_error": "lost"},
                       {"process_started": False}):
            result = classify_coding_capture({**capture, **change}, CodingEventObserver())
            self.assertNotIn("startup_phase", result)
        observer = CodingEventObserver()
        observer.feed(b'{"type":"thread.started","thread_id":"T"}\n{"type":"turn.started"}\n')
        result = classify_coding_capture(capture, observer)
        self.assertNotIn("startup_phase", result)


class PreparationTests(BuildRuntimeTests):
    # Reuse the fixture without collecting its inherited tests a second time.
    def test_public_client_state_source_is_rejected_before_attempt(self):
        self.plan["workpacks"][0]["executor"] = "CODEX"
        self.plan["workpacks"][0].pop("local_argv")
        self.scope.update(model="TEST-MODEL", allow_model_service=True)
        state = self.root / "client-state"
        public = state / "public"
        public.mkdir(parents=True)
        self.scope["source_read_roots"].append(str(public))
        with patch("harness_foundry_factory.coding_process.client_state_root", return_value=state):
            with self.assertRaisesRegex(RequestValidationError, "authentication/state"):
                self.prepare(approve=False)
        self.assertFalse(self.events("BUILD_ATTEMPT_STARTED"))
        self.assertFalse(self.events("BUILD_AUTHORIZATION_PREPARED"))

    def test_local_only_scope_does_not_acquire_model_state_restriction(self):
        self.scope["source_read_roots"].append(str(self.source))
        with patch("harness_foundry_factory.coding_process.client_state_root", return_value=self.source):
            self.prepare(approve=False)
        self.assertEqual(len(self.events("BUILD_AUTHORIZATION_PREPARED")), 1)

    def test_preparation_keeps_alias_origin_and_original_writable_alias_rejection(self):
        alias = self.root / "codex-alias"; alias.symlink_to("/usr/bin/true")
        self.scope["codex_executable"] = str(alias)
        self.prepare(approve=False)
        prepared = self.events("BUILD_AUTHORIZATION_PREPARED")[0]["payload"]
        self.assertEqual(prepared["scope"]["codex_executable"], str(Path("/usr/bin/true").resolve()))
        self.assertEqual(prepared["codex_receiver_binding"]["declared_executable"], str(alias))
        replay = prepare_build_scope(self.store, self.ir, self.plan,
            self.events("BUILD_SOURCES_CAPTURED")[0]["payload"], prepared["scope"], created_at="2026-09-18T00:00:00Z",
            prepared_preview={k:v for k,v in prepared.items() if k in {
                "scope", "verifier_files", "codex_receiver_binding", "acceptance_contracts"}})
        self.assertEqual(replay["codex_receiver_binding"], prepared["codex_receiver_binding"])

    def test_sync_failure_remains_one_charged_attempt_after_recovery(self):
        from harness_foundry_factory.build_runtime import BuildController
        from tests.test_build_runtime import CLOCK
        self._codex_fixture_runner([])
        self.prepare()
        config = self.workspace / ".codex/config.toml"
        config.parent.mkdir(); config.write_text("extra=1")
        controller = BuildController(self.store, self.program, runner=NativeBuildRunner(), clock=CLOCK)
        with patch("harness_foundry_factory.local_process.subprocess.Popen") as popen:
            first = controller.advance(self.prepared_id)
            controller.advance(self.prepared_id)
            popen.assert_not_called()
        attempts = self.events("BUILD_ATTEMPT_STARTED")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "BLOCKED", first)
        observations = self.events("BUILD_COMMAND_OBSERVED")
        self.assertEqual(len(observations), 1)
        self.assertFalse(observations[0]["payload"]["result"]["model_process_started"])

    def test_preview_identity_drift_blocks_confirmation_and_original_restore_is_legal(self):
        from tests.test_build_preview import BuildPreviewTests
        fixture = BuildPreviewTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        alias = fixture.f.root / "codex-alias"; alias.symlink_to("/usr/bin/true")
        fixture.request["scope"]["codex_executable"] = str(alias)
        preview = fixture.preview(); request = fixture.confirm(preview)
        alias.unlink(); alias.symlink_to("/usr/bin/false")
        with self.assertRaisesRegex(RequestValidationError, "displayed preparation changed"):
            fixture.materialize(request)
        self.assertFalse(fixture.db.exists())
        alias.unlink(); alias.symlink_to("/usr/bin/true")
        result = fixture.materialize(request)
        self.assertEqual(result["status"], "BUILD_PREVIEW_MATERIALIZED")
        self.assertFalse(any(e['event_type']=='BUILD_ATTEMPT_STARTED' for e in fixture.events()))


def load_tests(loader, tests, pattern):
    suite = loader.loadTestsFromTestCase(ReceiverBindingTests)
    suite.addTests(loader.loadTestsFromTestCase(DispatchTests))
    for name in PreparationTests.__dict__:
        if name.startswith("test_"):
            suite.addTest(PreparationTests(name))
    return suite
