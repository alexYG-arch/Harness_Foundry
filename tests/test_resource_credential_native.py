"""Native synthetic credential calls and durable recovery; no external provider."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_runtime import NativeBuildRunner
import test_build_resources as resource_support
import test_build_runtime as support


TOKEN_A = "SYNTHETIC_ONLY_caf\u00e9_API_TOKEN_first_9c2f7d6e0b14"
TOKEN_B = "SYNTHETIC_ONLY_caf\u00e9_API_TOKEN_rotated_873b11e1a294"
TOKEN_ENV = "FOUNDRY_TEST_API_TOKEN"

AUTHENTICATED_CALL = r'''
import http.client, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
token = os.environ['FOUNDRY_CREDENTIAL_API_TOKEN']
assert 'FOUNDRY_TEST_API_TOKEN' not in os.environ
authorized_calls = []
class AuthenticatedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        authorized = self.headers.get('Authorization') == 'Bearer ' + token
        self.send_response(200 if authorized else 401)
        self.end_headers()
        if authorized:
            authorized_calls.append(os.environ['FOUNDRY_COMMAND_ID'])
            self.wfile.write(os.environ['FOUNDRY_COMMAND_ID'].encode())
    def log_message(self, *args):
        pass
service = HTTPServer(('127.0.0.1', 0), AuthenticatedHandler)
endpoint = service.server_address
thread = threading.Thread(target=service.serve_forever)
thread.start()
auth_statuses = []
try:
    for supplied in (None, 'deliberately-incorrect-synthetic-token', token):
        client = http.client.HTTPConnection(*endpoint, timeout=2)
        try:
            headers = {} if supplied is None else {'Authorization': 'Bearer ' + supplied}
            client.request('GET', '/test-api', headers=headers)
            response = client.getresponse()
            auth_statuses.append(response.status)
            payload = response.read()
            if supplied == token:
                assert payload == os.environ['FOUNDRY_COMMAND_ID'].encode()
        finally:
            client.close()
finally:
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)
    assert not thread.is_alive()
assert auth_statuses == [401, 401, 200]
assert authorized_calls == [os.environ['FOUNDRY_COMMAND_ID']]
# Deliberately emit a synthetic secret in separate pipe writes. The controller
# must sanitize before persistence, including a UTF-8 codepoint split.
encoded = token.encode()
unicode_boundary = encoded.index(b'\xc3') + 1
for descriptor in (1, 2):
    os.write(descriptor, b'SYNTHETIC_AUTH_DIAGNOSTIC ')
    for fragment in (encoded[:8], encoded[8:unicode_boundary], encoded[unicode_boundary:]):
        os.write(descriptor, fragment)
        time.sleep(0.03)
    os.write(descriptor, b'\n')
Path(os.environ['FOUNDRY_REPORT_DIR'], 'auth.txt').write_text('Bearer ' + token + '\n')
'''

REPORT_AUTH_FIELDS = r'''
report['checks'].append({'id': 'authentication', 'status': 'PASS'})
report['services_stopped'] = True
report['auth_statuses'] = auth_statuses
report['authorized_call_count'] = len(authorized_calls)
report['test_credential_diagnostic'] = token
report['service_endpoint'] = {'host': endpoint[0], 'port': endpoint[1]}
'''

CREDENTIAL_CHECKER = resource_support.RESOURCE_CHECKER.replace(
    'report = {"schema_version": "1.0",',
    AUTHENTICATED_CALL + '\nreport = {"schema_version": "1.0",',
).replace('if mode != "missing":', REPORT_AUTH_FIELDS + '\nif mode != "missing":')


@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "native receiver opt-in required")
class NativeResourceCredentialTests(unittest.TestCase):
    def fixture(self):
        holder = resource_support.BuildResourceIntegrationTests()
        self.addCleanup(holder.doCleanups)
        fixture = holder.fixture()
        fixture.scope["codex_executable"] = os.environ["HFFACTORY_TEST_CODEX_SANDBOX"]
        fixture.scope["command_timeout_seconds"] = 30
        fixture.scope["source_read_roots"] += [str(Path(sys._base_executable).parent),
            *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]
        profile = fixture.scope["verification_resources"]["profiles"]["local"]
        profile["network"] = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"}
        profile["credentials"] = {"API_TOKEN": {
            "ref": "env:" + TOKEN_ENV, "purpose": "测试服务认证"}}
        profile["report_files"].append("auth.txt")
        profile["required_checks"].append("authentication")
        (fixture.verifier / "check.py").write_text(CREDENTIAL_CHECKER)
        return fixture

    def check_no_persisted_secrets(self, fixture, *tokens):
        # The source environment is deliberately absent from persisted state.
        # Check both serialized event bodies and every host-owned attachment,
        # not only the human readback or bounded stdout preview.
        serialized = json.dumps(fixture.events(), ensure_ascii=False).encode()
        database = fixture.store.database_path
        files = [path for path in (database, Path(str(database) + "-wal"),
                                  Path(str(database) + "-shm")) if path.is_file()]
        commands = database.with_suffix(".commands")
        files += [path for path in commands.rglob("*") if path.is_file()]
        for token in tokens:
            for encoded in (token.encode(), json.dumps(token, ensure_ascii=True)[1:-1].encode()):
                self.assertNotIn(encoded, serialized, "credential leaked into the event ledger")
                for path in files:
                    self.assertNotIn(encoded, path.read_bytes(), f"credential leaked into {path.name}")

    def crash_after_completed_check(self, fixture):
        native = NativeBuildRunner()
        invocations, crashed, captures = [], [], []

        def runner(invocation, before_dispatch):
            invocations.append({key: deepcopy(value) for key, value in invocation.items() if not callable(value)})
            result = native(invocation, before_dispatch)
            captures.append(result)
            if invocation["phase"] == "VERIFICATION" and not crashed:
                crashed.append(invocation["command_id"])
                raise support.InjectedControllerCrash()
            return result

        fixture.runner = runner
        fixture.prepare()
        with patch.dict(os.environ, {TOKEN_ENV: TOKEN_A}), self.assertRaises(support.InjectedControllerCrash):
            fixture.advance()
        self.assertEqual(captures[-1]["status"], "PASS", captures[-1])
        self.check_no_persisted_secrets(fixture, TOKEN_A)
        return invocations, crashed[0]

    def check_successful_observation(self, command):
        outcome = command["result"]
        self.assertEqual(outcome["status"], "PASS", outcome)
        self.assertEqual(outcome["receiver"], "CODEX_SANDBOX_PERMISSION_PROFILE")
        report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
        self.assertEqual(report["command_id"], command["command_id"])
        self.assertEqual(report["case_id"], command["case_id"])
        self.assertEqual(report["auth_statuses"], [401, 401, 200])
        self.assertEqual(report["authorized_call_count"], 1)
        self.assertTrue(report["services_stopped"])
        self.assertNotIn(report["test_credential_diagnostic"], (TOKEN_A, TOKEN_B))
        self.assertEqual(outcome["resource_cleanup"]["status"], "CLEANED")
        self.assertTrue((Path(command["observation_root"]) / "reports/auth.txt").is_file())
        for area in command["resource_binding"]["areas"].values():
            self.assertFalse(Path(area).exists())

    def test_native_bearer_auth_and_secret_free_recovery_after_token_rotation(self):
        fixture = self.fixture()
        invocations, completed_id = self.crash_after_completed_check(fixture)
        with patch.dict(os.environ, {TOKEN_ENV: TOKEN_B}):
            result = fixture.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(invocations), 5, "completed authenticated call must not run again")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 2)
        checks = [event["payload"] for event in fixture.events("BUILD_COMMAND_OBSERVED")
                  if event["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(checks), 3)
        self.assertEqual(sum(command["command_id"] == completed_id for command in checks), 1)
        for command in checks:
            self.check_successful_observation(command)
        self.check_no_persisted_secrets(fixture, TOKEN_A, TOKEN_B)
        self.assertEqual((fixture.workspace / "src/reader.py").read_text(), support.GOOD_READER)

    def test_completed_call_recovers_without_old_token_but_missing_new_call_does_not_repair(self):
        fixture = self.fixture()
        invocations, completed_id = self.crash_after_completed_check(fixture)
        with patch.dict(os.environ):
            os.environ.pop(TOKEN_ENV, None)
            result = fixture.advance()
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(sum(row["phase"] == "IMPLEMENTATION" for row in invocations), 1)
        self.assertFalse(fixture.events("BUILD_ACCEPTANCE_INVALIDATED"))
        observed = [event["payload"] for event in fixture.events("BUILD_COMMAND_OBSERVED")
                    if event["payload"]["phase"] == "VERIFICATION"]
        recovered = [command for command in observed if command["command_id"] == completed_id]
        self.assertEqual(len(recovered), 1)
        self.check_successful_observation(recovered[0])
        denied = [command for command in observed if command["command_id"] != completed_id]
        self.assertEqual(len(denied), 1)
        self.assertFalse(denied[0]["result"]["automatic_retry_allowed"])
        self.assertFalse(denied[0]["result"]["workload_started"])
        started = [event["payload"] for event in fixture.events("BUILD_COMMAND_STARTED")
                   if event["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual([command["command_id"] for command in started], [completed_id])
        self.check_no_persisted_secrets(fixture, TOKEN_A)


if __name__ == "__main__":
    unittest.main()
