"""Explicit loopback plus owned Unix access; no implicit scope expansion."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_runtime import NativeBuildRunner
from harness_foundry_factory.build_types import RequestValidationError
from harness_foundry_factory.local_process import LocalProcessError
from harness_foundry_factory.resource_network import effective_network_policy
from harness_foundry_factory.verification_resources import validate_resources
import test_resource_network as network_support
import test_verification_resources as verification_support
import test_build_resources as resource_support
import test_build_runtime as support


class CombinedNetworkContractTests(unittest.TestCase):
    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_explicit_combination_preserves_both_permissions_and_policy(self):
        f = self.fixture(network_support.ResourceNetworkContractTests)
        network = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK",
                   "unix_sockets": [str(f.scratch / "owned.sock")]}
        command = f.command(network=network)
        self.assertEqual(command.network, network)
        self.assertTrue(command.permission_profile()["network"]["allow_local_binding"])
        policy = effective_network_policy(command.network)
        self.assertEqual(policy["unix_sockets"], network["unix_sockets"])
        self.assertEqual(policy["loopback_protocols"], ["TCP", "UDP"])
        self.assertEqual(policy["external_network"], "DENY_EXCEPT_NATIVE_DNS_PORT_53")
        self.assertEqual(policy["guarantee"], "LOOPBACK_ALL_PORTS_NOT_SERVICE_ISOLATION")
        alias = f.scratch / "alias"
        alias.symlink_to(f.scratch, target_is_directory=True)
        bad = [network | {"tcp": "ANY"}, network | {"allowed_hosts": ["example.com"]},
               network | {"unix_sockets": []},
               network | {"unix_sockets": [network["unix_sockets"][0]] * 2},
               network | {"unix_sockets": [str(f.root / "outside.sock")]},
               network | {"unix_sockets": [str(alias / "service.sock")]},
               network | {"unix_sockets": [str(f.scratch / "../outside.sock")]},
               {"mode": "REMOTE_SERVICE", "allowed_hosts": ["example.com"], "tcp": "LOOPBACK"}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(LocalProcessError):
                f.command(network=value)

    def test_combined_argv_and_missing_capability_never_dispatch_workload(self):
        f = self.fixture(network_support.ResourceNetworkContractTests)
        network = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK",
                   "unix_sockets": [str(f.scratch / "owned.sock")]}
        command = f.command(network=network)
        help_result = {"exit_code": 0, "timed_out": False, "stdout":
            "[COMMAND] --permission-profile --include-managed-config --cd --allow-unix-socket", "stderr": ""}
        active = help_result | {"stdout": "1\n"}
        with patch.object(f.runner, "_capture", side_effect=[help_result, active, active, active]) as capture:
            result = f.runner.run(command)
        self.assertEqual(result["status"], "PASS")
        for call in capture.call_args_list[1:]:
            argv = call.args[0]
            self.assertIn("features.network_proxy=true", argv)
            self.assertEqual(argv[argv.index("--allow-unix-socket") + 1], network["unix_sockets"][0])
        for outputs, reason in (([help_result | {"stdout": help_result["stdout"].replace("--allow-unix-socket", "")}],
                                 "SANDBOX_UNIX_SOCKET_INTERFACE_UNAVAILABLE"),
                                ([help_result, active | {"stdout": "0"}], "SANDBOX_PROXY_NOT_ACTIVE"),
                                ([help_result, active, active | {"stdout": "0"}], "SANDBOX_LOCAL_TCP_NOT_ACTIVE")):
            with self.subTest(reason=reason), patch.object(f.runner, "_capture", side_effect=outputs) as capture:
                result = f.runner.run(command)
            self.assertEqual(result["reason_code"], reason)
            self.assertFalse(result["workload_started"])
            self.assertEqual(capture.call_count, len(outputs))

    def test_resource_resolution_preserves_combination_and_rejects_invalid_refs(self):
        f = self.fixture(verification_support.VerificationResourcesTests)
        network = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK",
                   "unix_sockets": ["resource://scratch/owned/service.sock"]}
        f.config["profiles"]["sqlite"]["network"] = network
        binding = f.binding()
        self.assertEqual(binding["network"]["tcp"], "LOOPBACK")
        self.assertEqual(binding["network"]["unix_sockets"],
                         [str(Path(binding["areas"]["scratch"]) / "owned/service.sock")])
        self.assertEqual(binding["profile"]["network"], network)
        for value in (network | {"tcp": "ANY"}, network | {"unexpected": True},
                      network | {"unix_sockets": []},
                      network | {"unix_sockets": network["unix_sockets"] * 2},
                      network | {"unix_sockets": ["resource://report-staging/service.sock"]},
                      network | {"unix_sockets": ["resource://scratch/../service.sock"]}):
            f.config["profiles"]["sqlite"]["network"] = value
            with self.subTest(value=value), self.assertRaises(RequestValidationError):
                validate_resources(f.config, f.plan)


COMBINED_CALL = r'''
import http.client, socket, socketserver, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
calls = {'tcp': 0, 'unix': 0}
class CombinedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        calls[self.server.kind] += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write((self.server.kind + ':' + os.environ['FOUNDRY_COMMAND_ID']).encode())
    def log_message(self, *args): pass
product_cwd = os.getcwd()
os.chdir(scratch)
try:
    unix_service = socketserver.UnixStreamServer('service.sock', CombinedHandler)
finally:
    os.chdir(product_cwd)
tcp_service = HTTPServer(('127.0.0.1', 0), CombinedHandler)
endpoint = tcp_service.server_address
services = [tcp_service, unix_service]
threads = []
try:
    for server, kind in zip(services, ('tcp', 'unix')):
        server.kind = kind
        thread = threading.Thread(target=server.serve_forever)
        thread.start(); threads.append(thread)
    for kind in ('tcp', 'unix'):
        client = http.client.HTTPConnection(*endpoint, timeout=2)
        if kind == 'unix':
            client.sock = socket.socket(socket.AF_UNIX)
            client.sock.settimeout(2)
            os.chdir(scratch)
            try: client.sock.connect('service.sock')
            finally: os.chdir(product_cwd)
        try:
            client.request('GET', '/ready')
            response = client.getresponse()
            assert response.status == 200
            assert response.read() == (kind + ':' + os.environ['FOUNDRY_COMMAND_ID']).encode()
        finally: client.close()
finally:
    for server in services: server.shutdown(); server.server_close()
    for thread in threads: thread.join(timeout=2); assert not thread.is_alive()
    (scratch / 'service.sock').unlink()
assert calls == {'tcp': 1, 'unix': 1}
with socket.socket() as client:
    try: client.connect(endpoint)
    except ConnectionRefusedError: pass
    else: raise AssertionError('TCP listener leaked')
with socket.socket(socket.AF_UNIX) as forbidden:
    os.chdir(scratch)
    try:
        try: forbidden.bind('undeclared.sock')
        except PermissionError: pass
        else: raise AssertionError('undeclared Unix socket allowed')
    finally: os.chdir(product_cwd)
with socket.socket() as forbidden:
    forbidden.settimeout(1)
    try: forbidden.connect(('192.0.2.1', 12345))
    except PermissionError: pass
    else: raise AssertionError('non-loopback direct connection allowed')
'''
COMBINED_FIELDS = r'''
report['checks'].append({'id': 'combined-service', 'status': 'PASS'})
report['services_stopped'] = True
report['service_request_counts'] = calls
report['service_endpoint'] = {'host': endpoint[0], 'port': endpoint[1]}
'''
COMBINED_CHECKER = resource_support.RESOURCE_CHECKER.replace(
    'report = {"schema_version": "1.0",', COMBINED_CALL + '\nreport = {"schema_version": "1.0",'
).replace('if mode != "missing":', COMBINED_FIELDS + '\nif mode != "missing":')


@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "native receiver opt-in required")
class NativeCombinedNetworkTests(unittest.TestCase):
    def fixture(self, mode="normal"):
        holder = resource_support.BuildResourceIntegrationTests()
        self.addCleanup(holder.doCleanups)
        fixture = holder.fixture(mode=mode)
        fixture.scope["codex_executable"] = os.environ["HFFACTORY_TEST_CODEX_SANDBOX"]
        fixture.scope["command_timeout_seconds"] = 30
        fixture.scope["source_read_roots"] += [str(Path(sys._base_executable).parent),
            *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]
        profile = fixture.scope["verification_resources"]["profiles"]["local"]
        profile["network"] = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK",
                              "unix_sockets": ["resource://scratch/service.sock"]}
        profile["required_checks"].append("combined-service")
        (fixture.verifier / "check.py").write_text(COMBINED_CHECKER)
        return fixture

    def test_combined_native_capture_recovery_and_cleaned_report_reuse(self):
        f = self.fixture()
        native, invocations, crashed = NativeBuildRunner(), [], []
        def runner(invocation, before_dispatch):
            invocations.append((invocation["phase"], invocation["command_id"]))
            result = native(invocation, before_dispatch)
            if invocation["phase"] == "VERIFICATION" and not crashed:
                self.assertEqual(result["status"], "PASS", result)
                crashed.append(invocation["command_id"])
                raise support.InjectedControllerCrash()
            return result
        f.runner = runner
        f.prepare()
        with self.assertRaises(support.InjectedControllerCrash): f.advance()
        result = f.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        old_invocations = deepcopy(invocations)
        old_events = deepcopy(f.events())
        self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(invocations, old_invocations)
        self.assertEqual(f.events(), old_events)
        self.assertEqual(len(invocations), 5)
        self.assertEqual(len(f.events("BUILD_ATTEMPT_STARTED")), 2)
        commands = [e["payload"] for e in f.events("BUILD_COMMAND_OBSERVED")
                    if e["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(commands), 3)
        self.assertEqual(sum(row["command_id"] == crashed[0] for row in commands), 1)
        for command in commands:
            result = command["result"]
            self.assertEqual(result["status"], "PASS", result)
            policy = result["effective_network_policy"]
            self.assertEqual(policy["tcp"], "LOOPBACK")
            self.assertEqual(policy["unix_sockets"], command["resource_binding"]["network"]["unix_sockets"])
            report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
            self.assertEqual(report["command_id"], command["command_id"])
            self.assertEqual(report["service_request_counts"], {"tcp": 1, "unix": 1})
            self.assertTrue(report["services_stopped"])
            self.assertEqual(result["resource_cleanup"]["status"], "CLEANED")
            for area in command["resource_binding"]["areas"].values(): self.assertFalse(Path(area).exists())

    def test_combined_known_failure_preserves_reports_and_closes_services(self):
        f = self.fixture(mode="error")
        f.runner = NativeBuildRunner()
        f.prepare()
        result = f.advance()
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        commands = [e["payload"] for e in f.events("BUILD_COMMAND_OBSERVED")
                    if e["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command["result"]["resource_cleanup"]["status"], "RETAINED")
        report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
        self.assertEqual(report["service_request_counts"], {"tcp": 1, "unix": 1})
        self.assertTrue(report["services_stopped"])
        self.assertFalse(Path(command["resource_binding"]["network"]["unix_sockets"][0]).exists())
