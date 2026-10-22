"""Opt-in resource receiver tests; native evidence remains explicitly separate."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.local_process import CodexSandboxRunner, LocalCommand, LocalProcessError
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.resource_network import effective_network_policy, normalize_network


class ResourceNetworkContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.runner = CodexSandboxRunner("/usr/bin/true")

    def command(self, **extra):
        return LocalCommand.prepare(argv=["/usr/bin/true"], cwd=self.root,
            read_roots=[self.root, "/usr/bin/true"], write_roots=[self.scratch], **extra)

    def test_offline_default_and_explicit_resources_are_compatible(self):
        self.assertEqual(self.command().permission_profile()["network"], {"enabled": False})
        command = self.command(environment={"TMPDIR": str(self.scratch)}, network={"mode": "NONE"})
        self.assertEqual(command.permission_profile()["network"], {"enabled": False})
        self.assertEqual(dict(command.environment), {"TMPDIR": str(self.scratch)})

    def test_environment_does_not_open_inherited_configuration_or_other_paths(self):
        for environment in ({"HOME": str(self.root)}, {"PYTHONPATH": str(self.root)},
                            {"HTTPS_PROXY": "http://example.com"}, {"TMPDIR": str(self.root)}):
            with self.subTest(environment=environment), self.assertRaises(LocalProcessError):
                self.command(environment=environment)

    def test_only_owned_exact_socket_paths_are_allowed(self):
        network = {"mode": "LOCAL_SERVICE", "unix_sockets": [str(self.scratch / "service.sock")]}
        self.assertEqual(self.command(network=network).network, network)
        self.assertFalse(self.command(network=network).permission_profile()["network"]["enabled"])
        for path in (str(self.root / "outside.sock"), "service.sock", str(self.scratch / "../outside.sock")):
            with self.subTest(path=path), self.assertRaises(LocalProcessError):
                self.command(network={"mode": "LOCAL_SERVICE", "unix_sockets": [path]})

    def test_remote_host_contract_does_not_silently_strip_port_or_operation(self):
        for host in ("https://example.com", "example.com:443", "example.com/path", "*.example.com"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                normalize_network({"mode": "REMOTE_SERVICE", "allowed_hosts": [host]})
        command = self.command(network={"mode": "REMOTE_SERVICE", "allowed_hosts": ["EXAMPLE.COM"]})
        policy = command.permission_profile()["network"]
        self.assertEqual(policy["domains"], {"example.com": "allow"})
        self.assertFalse(policy["allow_upstream_proxy"])

    def test_tcp_is_explicit_loopback_scope_without_implicit_remote_grant(self):
        network = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"}
        command = self.command(network=network)
        self.assertEqual(command.network, network)
        policy = command.permission_profile()["network"]
        self.assertEqual(policy, {"enabled": True,
            "domains": {"localhost": "allow", "127.0.0.1": "allow", "::1": "allow"},
            "proxy_url": "http://127.0.0.1:0", "enable_socks5": False,
            "allow_upstream_proxy": False, "allow_local_binding": True})
        observed = effective_network_policy(network)
        self.assertEqual(observed["loopback_protocols"], ["TCP", "UDP"])
        self.assertEqual(observed["enforcement"], "CODEX_NATIVE_LOOPBACK_TCP")
        for bad in ({"mode": "LOCAL_SERVICE", "tcp": True},
                    {"mode": "LOCAL_SERVICE", "tcp": "ANY"},
                    network | {"ports": [8000]}, network | {"allowed_hosts": ["example.com"]}):
            with self.subTest(bad=bad), self.assertRaises(LocalProcessError):
                self.command(network=bad)

    def test_tcp_checks_both_capabilities_before_dispatch_with_same_budget(self):
        help_result = {"exit_code": 0, "timed_out": False, "stdout":
            "[COMMAND] --permission-profile --include-managed-config --cd", "stderr": ""}
        active = help_result | {"stdout": "1\n"}
        completed = help_result | {"stdout": ""}
        command = self.command(timeout_seconds=10, network={"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"})
        with patch("harness_foundry_factory.local_process.time.monotonic", side_effect=[0, 1, 3, 5, 7]), \
                patch.object(self.runner, "_capture", side_effect=[help_result, active, active, completed]) as capture:
            result = self.runner.run(command)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([call.args[2] for call in capture.call_args_list], [9, 7, 5, 3])
        self.assertEqual(capture.call_args_list[1].args[0][-2:], ["/usr/bin/printenv", "CODEX_NETWORK_PROXY_ACTIVE"])
        self.assertEqual(capture.call_args_list[2].args[0][-2:], ["/usr/bin/printenv", "CODEX_NETWORK_ALLOW_LOCAL_BINDING"])
        for local_marker in ("", "0", "1\n0"):
            with self.subTest(local_marker=local_marker), \
                    patch.object(self.runner, "_capture", side_effect=[help_result, active, completed | {"stdout": local_marker}]) as capture:
                result = self.runner.run(command)
                self.assertEqual(result["reason_code"], "SANDBOX_LOCAL_TCP_NOT_ACTIVE")
                self.assertFalse(result["workload_started"])
                self.assertEqual(capture.call_count, 3)

    def test_proxy_must_be_active_before_workload_dispatch(self):
        help_result = {"exit_code": 0, "timed_out": False, "stdout":
            "[COMMAND] --permission-profile --include-managed-config --cd --allow-unix-socket", "stderr": ""}
        inactive = help_result | {"stdout": ""}
        command = self.command(network={"mode": "REMOTE_SERVICE", "allowed_hosts": ["example.com"]})
        with patch.object(self.runner, "_capture", side_effect=[help_result, inactive]) as capture:
            result = self.runner.run(command)
        self.assertEqual(result["reason_code"], "SANDBOX_PROXY_NOT_ACTIVE")
        self.assertFalse(result["workload_started"])
        self.assertEqual(capture.call_count, 2)
        self.assertIn("features.network_proxy=true", capture.call_args.args[0])

    def test_effective_policy_is_durable_before_recovery(self):
        received = []
        policy = effective_network_policy({"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"})
        with patch.dict(os.environ, {"UNDECLARED_SECRET": "not-forwarded"}):
            capture = self.runner._capture([sys.executable, "-B", "-c",
                "import os;print(os.environ.get('FOUNDRY_SCRATCH'));print(os.environ.get('UNDECLARED_SECRET'))"],
                self.root, 5, environment={"FOUNDRY_SCRATCH": str(self.scratch)},
                network_policy=policy, on_capture=received.append)
        self.assertEqual(capture["stdout"].splitlines(), [str(self.scratch), "None"])
        self.assertEqual(received[0]["effective_network_policy"], policy)
        result = self.runner._result(capture, "LOCAL_PROCESS_EXIT_ZERO", workload_started=None)
        self.assertEqual(result["network"], "LOCAL_SERVICE")

    def test_current_and_legacy_policy_recovery_preserves_saved_scope(self):
        current = effective_network_policy({"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"})
        legacy = {key: value for key, value in current.items() if key != "loopback_protocols"}
        for name, policy in (("current", current), ("legacy", legacy)):
            with self.subTest(name=name):
                journal = CommandObservation(self.root / name, "COMMAND", "LOCAL")
                try:
                    journal.captured({"exit_code": 0, "timed_out": False,
                                      "effective_network_policy": policy})
                finally:
                    journal.close()
                saved = (journal.root / "capture.json").read_bytes()
                for _ in range(2):
                    result = CommandObservation.recover(journal.root, "COMMAND", "LOCAL")
                    self.assertEqual(result["effective_network_policy"], policy)
                    self.assertEqual((journal.root / "capture.json").read_bytes(), saved)
                self.assertFalse((journal.root / "result.json").exists())

    def test_resource_preparation_and_workload_share_one_timeout(self):
        help_result = {"exit_code": 0, "timed_out": False, "stdout":
            "[COMMAND] --permission-profile --include-managed-config --cd", "stderr": ""}
        completed = help_result | {"stdout": ""}
        command = self.command(timeout_seconds=10, network={"mode": "NONE"})
        with patch("harness_foundry_factory.local_process.time.monotonic", side_effect=[0, 1, 4, 7]), \
                patch.object(self.runner, "_capture", side_effect=[help_result, completed, completed]) as capture:
            result = self.runner.run(command)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([call.args[2] for call in capture.call_args_list], [9, 6, 3])

    def test_exhausted_preparation_budget_does_not_dispatch_workload(self):
        help_result = {"exit_code": 0, "timed_out": False, "stdout":
            "[COMMAND] --permission-profile --include-managed-config --cd", "stderr": ""}
        command = self.command(timeout_seconds=10, network={"mode": "NONE"})
        with patch("harness_foundry_factory.local_process.time.monotonic", side_effect=[0, 1, 11]), \
                patch.object(self.runner, "_capture", return_value=help_result) as capture:
            result = self.runner.run(command)
        self.assertEqual(result["reason_code"], "RESOURCE_COMMAND_TIMEOUT_BEFORE_DISPATCH")
        self.assertFalse(result["workload_started"])
        self.assertEqual(capture.call_count, 1)
