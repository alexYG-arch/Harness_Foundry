"""Resource integration with disposable real Python processes.

These fixtures exercise controller bindings, SQLite, reports and recovery.  The
fixture runner deliberately bypasses the OS sandbox and makes no native receiver
or real external service qualification claim. Native tests cover that boundary.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_replan import adapt_build_plan
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_display import render_build_readback
from harness_foundry_factory.build_types import IdempotencyConflictError, RequestValidationError
from harness_foundry_factory.build_runtime import prepare_build_authorization
from harness_foundry_factory.local_process import classify_local_capture
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.resource_network import effective_network_policy
from harness_foundry_factory.resource_observation import finish_resource_observation
import test_build_runtime as support


RESOURCE_CHECKER = r'''import importlib.util, json, os, sqlite3, sys, tempfile
from pathlib import Path
assert Path(__file__).is_relative_to(Path(os.environ["FOUNDRY_VERIFIER_ROOT"]))
case, mode = sys.argv[1:3]
if case == "report":
    assert json.loads(Path("outputs/summary.json").read_text()) == {"rows": 3, "invalid": 2}
else:
    spec = importlib.util.spec_from_file_location("subject", Path("src/reader.py"))
    subject = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(subject)
    if case == "rows":
        assert subject.inspect_rows(["1", "bad", ""])["rows"] == 3
    else:
        try:
            subject.inspect_rows(None)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed input accepted")
scratch = Path(os.environ["FOUNDRY_SCRATCH_DIR"])
assert Path(os.environ["TMPDIR"]) == scratch
assert Path(tempfile.gettempdir()) == scratch
assert "FOUNDRY_FIXTURE_SECRET_NOT_AUTHORIZED" not in os.environ
with tempfile.TemporaryDirectory() as temporary:
    assert Path(temporary).is_relative_to(scratch)
    Path(temporary, "rows.txt").write_text("1\nbad\n\n")
    assert len(Path(temporary, "rows.txt").read_text().splitlines()) == 3
database = scratch / "test.sqlite3"
with sqlite3.connect(database) as db:
    assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    db.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO rows(value) VALUES ('committed')")
    db.commit()
    assert database.with_name(database.name + "-wal").exists()
    assert database.with_name(database.name + "-shm").exists()
    db.execute("INSERT INTO rows(value) VALUES ('rolled back')")
    db.rollback()
    db.execute("ALTER TABLE rows ADD COLUMN valid INTEGER DEFAULT 1")
    db.commit()
    assert db.execute("SELECT value, valid FROM rows").fetchall() == [("committed", 1)]
db.close()
with sqlite3.connect(database) as reopened:
    assert reopened.execute("SELECT COUNT(*) FROM rows").fetchone()[0] == 1
reopened.close()
service_endpoint = None
service_error = None
if mode == "local-service":
    import http.client, socket, socketserver, threading
    from http.server import BaseHTTPRequestHandler
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OWNED_INSTANCE_READY')
        def log_message(self, *args):
            pass
    product_cwd = os.getcwd()
    os.chdir(scratch)
    try:
        service = socketserver.UnixStreamServer('service.sock', Handler)
    finally:
        os.chdir(product_cwd)
    thread = threading.Thread(target=service.serve_forever)
    thread.start()
    try:
        client = http.client.HTTPConnection('owned-local-service')
        client.sock = socket.socket(socket.AF_UNIX)
        client.sock.settimeout(2)
        os.chdir(scratch)
        try:
            client.sock.connect('service.sock')
        finally:
            os.chdir(product_cwd)
        client.request('GET', '/ready')
        response = client.getresponse()
        assert response.status == 200 and response.read() == b'OWNED_INSTANCE_READY'
        client.close()
    finally:
        service.shutdown()
        service.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        (scratch / 'service.sock').unlink()
    assert os.getcwd() == product_cwd
elif mode in {"local-tcp", "local-tcp-start-failure"}:
    import errno, http.client, socket, threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    product_cwd = os.getcwd()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(os.environ['FOUNDRY_COMMAND_ID'].encode())
        def log_message(self, *args):
            pass
    if mode == "local-tcp-start-failure":
        # A startup collision is infrastructure failure, never evidence from
        # whatever listener already owns that port. Do not issue a request.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen(1)
            service_endpoint = occupied.getsockname()
            try:
                unexpected = HTTPServer(service_endpoint, Handler)
            except OSError as exc:
                assert exc.errno == errno.EADDRINUSE, exc
                service_error = 'OWNED_SERVICE_START_FAILED: address already in use'
            else:
                unexpected.server_close()
                raise AssertionError('conflicting service unexpectedly started')
    else:
        # Bind once and read the chosen endpoint from the owned listener.
        # No find-free-port/close/rebind window, and no inherited localhost proxy.
        service = HTTPServer(('127.0.0.1', 0), Handler)
        service_endpoint = service.server_address
        thread = threading.Thread(target=service.serve_forever)
        thread.start()
        client = http.client.HTTPConnection(*service_endpoint, timeout=2)
        try:
            client.request('GET', '/ready')
            response = client.getresponse()
            assert response.status == 200
            assert response.read() == os.environ['FOUNDRY_COMMAND_ID'].encode()
        finally:
            client.close()
            service.shutdown()
            service.server_close()
            thread.join(timeout=2)
            assert not thread.is_alive()
    assert os.getcwd() == product_cwd
elif mode == "remote-service":
    import urllib.request
    assert os.environ.get('CODEX_NETWORK_PROXY_ACTIVE') == '1'
    with urllib.request.urlopen('https://example.com/', timeout=10) as response:
        assert response.status == 200 and response.read(128)
report = {"schema_version": "1.0", "case_id": os.environ["FOUNDRY_CASE_ID"],
          "command_id": os.environ["FOUNDRY_COMMAND_ID"], "status": "CHECKS_PASS",
          "checks": [{"id": "temp", "status": "PASS"}, {"id": "sqlite", "status": "PASS"}],
          "errors": []}
if mode in {"local-service", "local-tcp", "local-tcp-start-failure"}:
    report["checks"].append({"id": "service", "status": "ERROR" if service_error else "PASS"})
    report["services_stopped"] = True
    if service_endpoint is not None:
        report["service_endpoint"] = {"host": service_endpoint[0], "port": service_endpoint[1]}
        report["product_cwd"] = product_cwd
    if service_error:
        report.update(status="CHECKS_FAILED", errors=[service_error])
elif mode == "remote-service":
    report["checks"].append({"id": "service", "status": "PASS"})
    report["external_effects"] = "NONE"
if mode == "stale":
    report["command_id"] = "COMMAND-OTHER-ATTEMPT"
elif mode == "wrong-case":
    report["case_id"] = "UNBOUND-CASE"
elif mode == "zero":
    report["checks"] = []
elif mode == "skipped":
    report["checks"][1]["status"] = "SKIP"
elif mode == "error":
    report["errors"] = ["database fixture unavailable"]
elif mode == "business-failure":
    report.update(status="CHECKS_FAILED", failure_kind="ASSERTION")
    report["checks"][1]["status"] = "FAIL"
if mode != "missing":
    Path(os.environ["FOUNDRY_REPORT_DIR"], "summary.json").write_text(json.dumps(report))
print("RESOURCE_CHECK_COMPLETE", report["case_id"])
if mode == "timeout-after-report":
    import time
    time.sleep(30)
raise SystemExit(1 if service_error or mode in {"business-failure", "exit-contradiction"} else 0)
'''


DEPENDENCY_CHECKER = r'''import importlib.util, json, os, runpy, sys
from pathlib import Path
case, mode = sys.argv[1:3]
verifier_root = Path(os.environ["FOUNDRY_VERIFIER_ROOT"])
# Fixed oracle input: explicit snapshot root, or an already hydrated verifier:// argument.
expected_path = Path(sys.argv[3]) if len(sys.argv) == 4 else verifier_root / "fixtures/expected.json"
helper_path = verifier_root / "oracle_helper.py"
spec = importlib.util.spec_from_file_location("bound_oracle", helper_path)
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
expected = json.loads(expected_path.read_text())
# Product inputs remain relative to the product cwd, not the checker snapshot.
if case == "report":
    actual = json.loads(Path("outputs/summary.json").read_text())
else:
    subject = runpy.run_path("src/reader.py")
    actual = subject["inspect_rows"](["1", "bad", ""])
passed = oracle.matches(actual, expected)
if case == "malformed":
    try:
        subject["inspect_rows"](None)
    except ValueError:
        pass
    else:
        passed = False
report = {"schema_version": "1.0", "case_id": os.environ["FOUNDRY_CASE_ID"],
          "command_id": os.environ["FOUNDRY_COMMAND_ID"],
          "status": "CHECKS_PASS" if passed else "CHECKS_FAILED",
          "checks": [{"id": "oracle", "status": "PASS" if passed else "FAIL"}], "errors": [],
          "oracle_files": [str(expected_path), str(helper_path)],
          "product_cwd": str(Path.cwd()), "expected": expected, "actual": actual}
if not passed:
    report["failure_kind"] = "ASSERTION"
Path(os.environ["FOUNDRY_REPORT_DIR"], "summary.json").write_text(json.dumps(report))
raise SystemExit(0 if passed else 1)
'''


def configure_dependency_fixture(fixture, access, reader):
    source = fixture.workspace / "tests"
    (source / "fixtures").mkdir(parents=True)
    (source / "check.py").write_text(DEPENDENCY_CHECKER)
    (source / "fixtures/expected.json").write_text('{"rows":3,"invalid":2}')
    (source / "oracle_helper.py").write_text('def matches(actual, expected):\n    return actual == expected\n')
    fixture.scope["verification_root"] = str(source)
    # Explicit argv dependencies are snapshotted automatically; do not require
    # callers to repeat them in checker_files.
    fixture.scope["verification_resources"]["checker_files"] = ["oracle_helper.py"]
    if access == "context":
        fixture.scope["verification_resources"]["checker_files"].append("fixtures/expected.json")
    else:
        for task in fixture.plan["workpacks"]:
            for check in task["verification"]:
                check["argv"].append("verifier://fixtures/expected.json")
    fixture.scope["verification_resources"]["profiles"]["local"]["required_checks"] = ["oracle"]
    fixture.plan["workpacks"][0]["local_argv"][-1] = fixture.write_reader(reader)
    return source


def change_product_oracle_files(source):
    # Mimic an implementation-side change to the test's expected output and
    # helper, plus a same-named cwd module. None may replace the approved oracle.
    (source / "fixtures/expected.json").write_text('{"rows":0,"invalid":0}')
    (source / "oracle_helper.py").write_text('def matches(actual, expected):\n    return True\n')
    (source.parent / "oracle_helper.py").write_text('def matches(actual, expected):\n    return True\n')


PRODUCT_COPY_TOOL = r'''import json, runpy
from pathlib import Path
# A real product-side tool uses paths relative to its project directory.
subject = runpy.run_path("src/reader.py")
dependency = json.loads(Path("tool-data/uncommitted.json").read_text())
Path(".cache/tool.json").write_text(json.dumps(dependency))
Path("build/result.json").write_text(json.dumps(subject["inspect_rows"](["1", "bad", ""])))
'''


PRODUCT_COPY_CHECKER = r'''import json, os, runpy, subprocess, sys
from pathlib import Path
case, mode = sys.argv[1:3]
product = Path(os.environ["FOUNDRY_PRODUCT_ROOT"])
verifier = Path(os.environ["FOUNDRY_VERIFIER_ROOT"])
assert Path.cwd() == product
assert Path(__file__).is_relative_to(verifier)
assert not product.is_relative_to(Path(os.environ["FOUNDRY_SCRATCH_DIR"]))
assert not Path(".cache/tool.json").exists(), "each command gets fresh generated outputs"
subprocess.run([sys.executable, "-I", "-B", "tools/build.py"], check=True)
actual = json.loads(Path("build/result.json").read_text())
dependency = json.loads(Path(".cache/tool.json").read_text())
expected = json.loads((verifier / "expected.json").read_text())
passed = actual == expected and dependency == {"revision": "after-prepare"}
if case == "report":
    passed = passed and json.loads(Path("outputs/summary.json").read_text()) == expected
elif case == "malformed":
    try:
        runpy.run_path("src/reader.py")["inspect_rows"](None)
    except ValueError:
        pass
    else:
        passed = False
denied = []
if mode == "native-boundaries":
    original = Path(ORIGINAL_WORKSPACE)
    for label, path in [("original-input", original / "src/reader.py"),
                        ("copied-input", product / "src/reader.py"),
                        ("checker", Path(__file__)),
                        ("undeclared-output", product / "undeclared.txt")]:
        try:
            with path.open("a") as stream:
                stream.write("\nUNAUTHORIZED_WRITE\n")
        except OSError:
            denied.append(label)
    passed = passed and len(denied) == 4
report = {"schema_version": "1.0", "case_id": os.environ["FOUNDRY_CASE_ID"],
          "command_id": os.environ["FOUNDRY_COMMAND_ID"],
          "status": "CHECKS_PASS" if passed else "CHECKS_FAILED",
          "checks": [{"id": "product", "status": "PASS" if passed else "FAIL"}], "errors": [],
          "product_cwd": str(product), "verifier_root": str(verifier),
          "actual": actual, "dependency": dependency, "denied_writes": denied}
if not passed:
    report["failure_kind"] = "ASSERTION"
Path(os.environ["FOUNDRY_REPORT_DIR"], "summary.json").write_text(json.dumps(report))
raise SystemExit(0 if passed else 1)
'''


def configure_product_copy_fixture(fixture, *, reader=support.GOOD_READER, native_boundaries=False):
    """Use declared working-tree files, including an untracked local dependency."""
    (fixture.workspace / "tools").mkdir()
    (fixture.workspace / "tool-data").mkdir()
    (fixture.workspace / "tools/build.py").write_text(PRODUCT_COPY_TOOL)
    (fixture.workspace / "tool-data/uncommitted.json").write_text('{"revision":"before-prepare"}')
    checker = PRODUCT_COPY_CHECKER.replace("ORIGINAL_WORKSPACE", repr(str(fixture.workspace)))
    (fixture.verifier / "check.py").write_text(checker)
    (fixture.verifier / "expected.json").write_text('{"rows":3,"invalid":2}')
    resources = fixture.scope["verification_resources"]
    resources["checker_files"] = ["expected.json"]
    profile = resources["profiles"]["local"]
    profile["required_checks"] = ["product"]
    profile["product_copy"] = {
        "files": ["src/reader.py", "tools/build.py", "tool-data/uncommitted.json"],
        "writable_paths": [".cache", "build"]}
    resources["profiles"]["report"] = deepcopy(profile)
    resources["profiles"]["report"]["product_copy"]["files"].append("outputs/summary.json")
    fixture.plan["workpacks"][0]["local_argv"][-1] = fixture.write_reader(reader)
    for task in fixture.plan["workpacks"]:
        for check in task["verification"]:
            check["argv"][-1] = "native-boundaries" if native_boundaries else "normal"
            if check["argv"][-2] == "report":
                check["resource_profile_ref"] = "report"


def update_product_copy_dependency(fixture):
    # Prepare freezes the independent oracle, not the current product inputs.
    (fixture.workspace / "tool-data/uncommitted.json").write_text('{"revision":"after-prepare"}')


class DurableResourceFixtureRunner:
    """Test-only subprocess runner with real host-owned observation attachments."""

    def __init__(self):
        self.invocations = []
        self.after_run = None

    def __call__(self, invocation, before_dispatch):
        before_dispatch()
        self.invocations.append({key: deepcopy(value) for key, value in invocation.items()
                                 if not callable(value)})
        assert invocation["executor"] == "LOCAL", "fixture cannot call a model"
        journal = CommandObservation(invocation["observation_root"], invocation["command_id"], "LOCAL",
                                     on_started=invocation.get("on_process_started"))
        environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", **invocation.get("environment", {})}
        try:
            process = subprocess.Popen(invocation["argv"], cwd=invocation["cwd"], env=environment,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            journal.started(process.pid)
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=invocation["timeout_seconds"])
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            journal.write("stdout", stdout)
            journal.write("stderr", stderr)
            capture = {"exit_code": process.returncode, "timed_out": timed_out,
                       "stdout": stdout.decode(), "stderr": stderr.decode(), "output_truncated": False,
                       "stream_bytes": {"stdout": len(stdout), "stderr": len(stderr)}}
            if "network" in invocation:
                capture["effective_network_policy"] = effective_network_policy(invocation["network"])
            journal.captured(capture)
            result = {**classify_local_capture(capture),
                      "receiver": "TEST_ONLY_LOCAL_PROCESS_NOT_SANDBOX_QUALIFICATION"}
            journal.finished(result)
        finally:
            journal.close()
        if self.after_run:
            self.after_run(invocation, result)
        return result


class BuildResourceIntegrationTests(unittest.TestCase):
    def fixture(self, mode="pass"):
        fixture = support.BuildRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.plan["schema_version"] = "1.2"
        resource_root = fixture.root / "verification-runs"
        resource_root.mkdir()
        fixture.scope["verification_resources"] = {
            "schema_version": "1.0", "root": str(resource_root), "profiles": {
                "local": {"writable_areas": ["scratch", "report-staging"],
                          "network": {"mode": "NONE"}, "services": [],
                          "result_protocol": "STRUCTURED_V1", "report_files": ["summary.json"],
                          "required_checks": ["temp", "sqlite"],
                          "retention": {"success": "REPORTS_ONLY", "failure_days": 7}}}}
        profile = fixture.scope["verification_resources"]["profiles"]["local"]
        if mode == "local-service":
            profile["network"] = {"mode": "LOCAL_SERVICE", "unix_sockets": ["resource://scratch/service.sock"]}
            profile["required_checks"].append("service")
        elif mode in {"local-tcp", "local-tcp-start-failure"}:
            profile["network"] = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"}
            profile["required_checks"].append("service")
        elif mode == "remote-service":
            profile["network"] = {"mode": "REMOTE_SERVICE", "allowed_hosts": ["example.com"]}
            profile["required_checks"].append("service")
        (fixture.verifier / "check.py").write_text(RESOURCE_CHECKER)
        for task in fixture.plan["workpacks"]:
            for check in task["verification"]:
                check["resource_profile_ref"] = "local"
                check["argv"].append(mode)
        fixture.runner = DurableResourceFixtureRunner()
        return fixture

    def check_product_copy_success(self, fixture, *, native_boundaries=False):
        commands = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(commands), 3)
        self.assertEqual(len({row["resource_binding"]["product_copy"]["root"] for row in commands}), 3)
        for command in commands:
            binding = command["resource_binding"]
            product = binding["product_copy"]
            self.assertEqual(product["source_root"], str(fixture.workspace))
            self.assertEqual(Path(product["root"]), Path(binding["root"]) / "product")
            self.assertFalse(Path(product["root"]).is_relative_to(Path(binding["areas"]["scratch"])))
            self.assertEqual(binding["env"]["FOUNDRY_PRODUCT_ROOT"], product["root"])
            self.assertNotIn(product["root"], binding["write_roots"])
            self.assertEqual(set(product["write_roots"]),
                             {str(Path(product["root"]) / path) for path in (".cache", "build")})
            for item in product["files"]:
                source = (fixture.workspace / item["path"]).read_bytes()
                self.assertEqual(item["copy"]["sha256"], hashlib.sha256(source).hexdigest())
                self.assertEqual(item["source"]["sha256"], item["copy"]["sha256"])
            outcome = command["result"]
            self.assertEqual(outcome["status"], "PASS", outcome)
            self.assertEqual(outcome["product_copy_validation"]["status"], "UNCHANGED")
            self.assertEqual(outcome["resource_cleanup"]["status"], "CLEANED")
            self.assertFalse(Path(product["root"]).exists())
            report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
            self.assertEqual(report["product_cwd"], product["root"])
            self.assertEqual(report["verifier_root"], binding["verifier_root"])
            self.assertEqual(report["actual"], {"rows": 3, "invalid": 2})
            self.assertEqual(report["dependency"], {"revision": "after-prepare"})
            if native_boundaries:
                self.assertEqual(set(report["denied_writes"]),
                                 {"original-input", "copied-input", "checker", "undeclared-output"})
                self.assertEqual(outcome["receiver"], "CODEX_SANDBOX_PERMISSION_PROFILE")
        self.assertFalse((fixture.workspace / ".cache").exists())
        self.assertFalse((fixture.workspace / "build").exists())
        self.assertFalse((fixture.workspace / "undeclared.txt").exists())
        self.assertEqual((fixture.workspace / "src/reader.py").read_text(), support.GOOD_READER)

    def test_product_copy_builds_relative_outputs_from_latest_uncommitted_inputs(self):
        fixture = self.fixture()
        configure_product_copy_fixture(fixture)
        checker = (fixture.verifier / "check.py").read_bytes()
        tool = (fixture.workspace / "tools/build.py").read_bytes()
        fixture.prepare()
        update_product_copy_dependency(fixture)
        result = fixture.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.check_product_copy_success(fixture)
        human = render_build_readback(read_build(fixture.store.database_path, fixture.program))
        for label in ("本次副本运行目录", "副本内可写生成目录", ".cache", "build", "正式产品不写入"):
            self.assertIn(label, human)
        self.assertEqual((fixture.verifier / "check.py").read_bytes(), checker)
        self.assertEqual((fixture.workspace / "tools/build.py").read_bytes(), tool)
        for invocation in fixture.runner.invocations:
            if invocation["phase"] == "VERIFICATION":
                self.assertEqual(invocation["cwd"], invocation["resource_binding"]["product_copy"]["root"])
                self.assertNotIn(str(fixture.workspace), invocation["write_roots"])
                self.assertEqual(invocation["network"], {"mode": "NONE"})
                self.assertIn(invocation["cwd"], human)

    def check_product_copy_wrong_product(self, *, fixture_factory=None):
        fixture = (fixture_factory or self.fixture)()
        configure_product_copy_fixture(fixture, reader=support.BAD_READER)
        fixture.prepare()
        update_product_copy_dependency(fixture)
        # A later product-side expectation cannot replace the approved checker oracle.
        (fixture.verifier / "expected.json").write_text('{"rows":0,"invalid":0}')
        result = fixture.controller().advance(fixture.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["attempt_status"], "REJECTED", result)
        commands = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertTrue(commands)
        for command in commands:
            outcome = command["result"]
            self.assertEqual(outcome["failure_domain"], "BUSINESS_ASSERTION")
            self.assertTrue(outcome["automatic_retry_allowed"])
            self.assertEqual(outcome["product_copy_validation"]["status"], "UNCHANGED")
            product = Path(command["resource_binding"]["product_copy"]["root"])
            self.assertTrue(product.is_dir(), "failed product copies remain available for diagnosis")
            self.assertEqual(json.loads((product / "build/result.json").read_text()), {"rows": 0, "invalid": 0})
        self.assertFalse((fixture.workspace / "build").exists())

    def test_product_copy_preserves_business_repair_and_failed_build_evidence(self):
        self.check_product_copy_wrong_product()

    def check_product_copy_recovery(self, *, after_cleanup=False, fixture_factory=None,
                                    native_boundaries=False):
        fixture = (fixture_factory or self.fixture)()
        configure_product_copy_fixture(fixture, native_boundaries=native_boundaries)
        fixture.prepare()
        update_product_copy_dependency(fixture)
        invocations, crashed = [], []
        original_runner = fixture.runner

        def runner(invocation, before_dispatch):
            invocations.append({key: deepcopy(value) for key, value in invocation.items() if not callable(value)})
            result = original_runner(invocation, before_dispatch)
            if not after_cleanup and invocation["phase"] == "VERIFICATION" and not crashed:
                crashed.append(invocation["command_id"])
                raise support.InjectedControllerCrash()
            return result

        def finish_then_interrupt(raw, binding, root):
            result = finish_resource_observation(raw, binding, root)
            if after_cleanup and not crashed:
                self.assertEqual(result["status"], "PASS", result)
                self.assertFalse(Path(binding["product_copy"]["root"]).exists())
                crashed.append(binding["command_id"])
                raise support.InjectedControllerCrash()
            return result

        fixture.runner = runner
        with patch("harness_foundry_factory.build_resource_lifecycle.finish_resource_observation", side_effect=finish_then_interrupt):
            with self.assertRaises(support.InjectedControllerCrash):
                fixture.advance()
        crashed_binding = next(row["resource_binding"] for row in invocations if row["command_id"] == crashed[0])
        self.assertEqual(Path(crashed_binding["product_copy"]["root"]).exists(), not after_cleanup)
        from harness_foundry_factory import build_resource_lifecycle
        materialize = build_resource_lifecycle.materialize_product_copy

        def only_new_commands(binding, workspace_root):
            self.assertNotEqual(binding["command_id"], crashed[0], "captured command must never recopy its product")
            return materialize(binding, workspace_root)

        with patch("harness_foundry_factory.build_resource_lifecycle.materialize_product_copy", side_effect=only_new_commands):
            result = fixture.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(invocations), 5, "two implementations plus three checks, without a repeated process")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 2)
        recovered = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                     if row["payload"]["command_id"] == crashed[0]]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["resource_binding"], crashed_binding)
        self.check_product_copy_success(fixture, native_boundaries=native_boundaries)
        revision = len(fixture.events())
        self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(invocations), 5)
        self.assertEqual(len(fixture.events()), revision)

    def test_product_copy_capture_recovery_does_not_recopy_redispatch_or_double_count(self):
        self.check_product_copy_recovery()

    def test_product_copy_cleaned_result_recovers_without_rebuilding_deleted_copy(self):
        self.check_product_copy_recovery(after_cleanup=True)

    def test_product_copy_source_change_before_acceptance_preserves_pass_without_accepting_new_bytes(self):
        fixture = self.fixture()
        configure_product_copy_fixture(fixture)
        fixture.prepare()
        update_product_copy_dependency(fixture)
        source = fixture.workspace / "tool-data/uncommitted.json"
        original = source.read_bytes()
        final_case = fixture.plan["workpacks"][-1]["verification"][-1]["case_id"]

        def edit_source_after_final_check(invocation, result):
            if invocation.get("case_id") == final_case:
                source.write_text('{"revision":"edited-after-check"}')

        fixture.runner.after_run = edit_source_after_final_check
        result = fixture.advance()
        self.assertEqual(result["status"], "BUILD_STOPPED", result)
        finished = fixture.events("BUILD_ATTEMPT_FINISHED")[-1]["payload"]
        self.assertEqual(finished["status"], "UNKNOWN_SIDE_EFFECT")
        final_command = fixture.events("BUILD_COMMAND_OBSERVED")[-1]["payload"]
        self.assertEqual(final_command["result"]["status"], "PASS", "old checker evidence stays factual")
        observation = Path(final_command["observation_root"])
        evidence = {path: path.read_bytes() for path in observation.rglob("*") if path.is_file()}
        root = Path(fixture.scope["verification_resources"]["root"])
        roots = sorted(root.iterdir())
        attempts = len(fixture.events("BUILD_ATTEMPT_STARTED"))
        calls = len(fixture.runner.invocations)
        self.assertEqual((attempts, calls), (2, 5))
        with patch("harness_foundry_factory.build_resource_lifecycle.materialize_product_copy",
                   side_effect=AssertionError("old copies must not be recreated")):
            for _ in range(2):
                held = fixture.advance()
                self.assertEqual(held["status"], "BUILD_STOPPED", held)
            self.assertEqual(sorted(root.iterdir()), roots)
            self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), attempts)
            self.assertEqual(len(fixture.runner.invocations), calls)
            source.write_bytes(original)
            self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(fixture.runner.invocations), calls)
        self.assertEqual({path: path.read_bytes() for path in evidence}, evidence)
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_RECOVERED")), 1)

    def test_product_copy_source_drift_does_not_repair_from_stale_business_failure(self):
        fixture = self.fixture()
        configure_product_copy_fixture(fixture, reader=support.BAD_READER)
        fixture.prepare()
        update_product_copy_dependency(fixture)
        source = fixture.workspace / "tool-data/uncommitted.json"
        original = source.read_bytes()
        final_case = fixture.plan["workpacks"][0]["verification"][-1]["case_id"]

        def edit_source_after_last_check(invocation, result):
            if invocation.get("case_id") == final_case:
                source.write_text('{"revision":"changed-after-business-failure"}')

        fixture.runner.after_run = edit_source_after_last_check
        one_attempt = lambda: fixture.controller().advance(fixture.prepared_id, advance_mode="ONE_ATTEMPT")
        result = one_attempt()
        self.assertEqual(result["attempt_status"], "UNKNOWN_SIDE_EFFECT", result)
        commands = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertEqual(command["result"]["failure_domain"], "BUSINESS_ASSERTION")
            self.assertTrue(command["result"]["automatic_retry_allowed"])
            self.assertEqual(command["result"]["resource_cleanup"]["status"], "RETAINED")
        evidence = {path: path.read_bytes() for command in commands
                    for path in Path(command["observation_root"]).rglob("*") if path.is_file()}
        with patch("harness_foundry_factory.build_resource_lifecycle.materialize_product_copy",
                   side_effect=AssertionError("stale failure cannot recreate copies or start repair")):
            self.assertEqual(one_attempt()["status"], "BUILD_STOPPED")
            source.write_bytes(original)
            recovered = one_attempt()
        self.assertEqual(recovered["attempt_status"], "REJECTED", recovered)
        self.assertEqual(recovered["budget"]["attempts_consumed"], 1)
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(len(fixture.runner.invocations), 3)
        self.assertEqual({path: path.read_bytes() for path in evidence}, evidence)
        for check in fixture.events("BUILD_ATTEMPT_RECOVERED")[-1]["payload"]["verification"]:
            self.assertTrue(check["result"]["automatic_retry_allowed"], "restored version keeps native repair eligibility")

    def check_product_copy_source_recovery(self, *, after_cleanup, final_check,
                                          fixture_factory=None, undeclared_change=False):
        fixture = (fixture_factory or self.fixture)()
        configure_product_copy_fixture(fixture)
        fixture.prepare()
        update_product_copy_dependency(fixture)
        target_case = (fixture.plan["workpacks"][-1]["verification"][-1]["case_id"] if final_check
                       else fixture.plan["workpacks"][0]["verification"][0]["case_id"])
        invocations, crashed = [], []
        original_runner = fixture.runner

        def runner(invocation, before_dispatch):
            invocations.append({key: deepcopy(value) for key, value in invocation.items() if not callable(value)})
            result = original_runner(invocation, before_dispatch)
            if not after_cleanup and invocation.get("case_id") == target_case and not crashed:
                self.assertEqual(result["status"], "PASS", result)
                crashed.append(invocation["command_id"])
                raise support.InjectedControllerCrash()
            return result

        def finish_then_interrupt(raw, binding, root):
            result = finish_resource_observation(raw, binding, root)
            if after_cleanup and binding["case_id"] == target_case and not crashed:
                self.assertEqual(result["status"], "PASS", result)
                self.assertFalse(Path(binding["product_copy"]["root"]).exists())
                crashed.append(binding["command_id"])
                raise support.InjectedControllerCrash()
            return result

        fixture.runner = runner
        with patch("harness_foundry_factory.build_resource_lifecycle.finish_resource_observation", side_effect=finish_then_interrupt):
            with self.assertRaises(support.InjectedControllerCrash):
                fixture.advance()
        command = next(row for row in invocations if row["command_id"] == crashed[0])
        binding = command["resource_binding"]
        self.assertEqual(Path(binding["product_copy"]["root"]).exists(), not after_cleanup)
        observation = Path(command["observation_root"])
        evidence = {path: path.read_bytes() for path in observation.rglob("*") if path.is_file()}
        source = fixture.workspace / "tool-data/uncommitted.json"
        original = source.read_bytes()
        if undeclared_change:
            (fixture.workspace / "unlisted-note.txt").write_text("ordinary unrelated edit")
        else:
            source.write_text('{"revision":"edited-while-interrupted"}')
        roots_path = Path(fixture.scope["verification_resources"]["root"])
        roots = sorted(roots_path.iterdir())
        attempts = len(fixture.events("BUILD_ATTEMPT_STARTED"))
        calls = len(invocations)
        from harness_foundry_factory import build_resource_lifecycle
        materialize = build_resource_lifecycle.materialize_product_copy
        old_commands = {row["command_id"] for row in invocations}

        def only_new_commands(resource_binding, workspace_root):
            self.assertNotIn(resource_binding["command_id"], old_commands,
                             "restoring a source must reuse the original checker evidence")
            return materialize(resource_binding, workspace_root)

        with patch("harness_foundry_factory.build_resource_lifecycle.materialize_product_copy", side_effect=only_new_commands):
            if not undeclared_change:
                for _ in range(2):
                    result = fixture.advance()
                    self.assertEqual(result["status"], "BUILD_STOPPED", result)
                self.assertEqual(len(invocations), calls, "changed source cannot dispatch remaining checks")
                self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), attempts)
                self.assertEqual(sorted(roots_path.iterdir()), roots)
                recovered = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                             if row["payload"]["command_id"] == crashed[0]]
                self.assertEqual(len(recovered), 1)
                self.assertEqual(recovered[0]["result"]["status"], "PASS", "do not rewrite historical success")
                source.write_bytes(original)
            result = fixture.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(invocations), 5, "two implementations and three original checks only")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 2)
        self.assertEqual({path: path.read_bytes() for path in evidence}, evidence)
        self.check_product_copy_success(fixture)
        events = len(fixture.events())
        self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(fixture.events()), events)
        self.assertEqual(len(invocations), 5)

    def test_product_copy_source_change_during_recovery_holds_without_recopy_replay_or_recount(self):
        for after_cleanup in (False, True):
            for final_check in (False, True):
                with self.subTest(after_cleanup=after_cleanup, final_check=final_check):
                    self.check_product_copy_source_recovery(after_cleanup=after_cleanup, final_check=final_check)

    def test_product_copy_undeclared_source_edit_does_not_block_recovery(self):
        self.check_product_copy_source_recovery(after_cleanup=True, final_check=True, undeclared_change=True)

    def test_product_copy_input_change_after_capture_withholds_acceptance_and_retains_evidence(self):
        fixture = self.fixture()
        configure_product_copy_fixture(fixture)
        fixture.prepare()
        update_product_copy_dependency(fixture)
        changed = []

        def change_copy_after_process(invocation, result):
            if invocation["phase"] == "VERIFICATION" and not changed:
                # A controlled host fixture changes a disposable copy after the
                # process exits; this is not a sandbox bypass or native claim.
                source = Path(invocation["resource_binding"]["product_copy"]["root"]) / "src/reader.py"
                source.chmod(0o600)
                source.write_text(support.BAD_READER)
                changed.append(source)

        fixture.runner.after_run = change_copy_after_process
        result = fixture.advance()
        self.assertNotEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        commands = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(commands), 1)
        outcome = commands[0]["result"]
        self.assertEqual(outcome["product_copy_validation"]["status"], "CHANGED")
        self.assertNotEqual(outcome["status"], "PASS")
        self.assertFalse(outcome["automatic_retry_allowed"])
        self.assertTrue(changed[0].exists())
        self.assertEqual((fixture.workspace / "src/reader.py").read_text(), support.GOOD_READER)
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)

    def test_product_copy_materialization_failure_is_durable_without_retry_or_dispatch(self):
        fixture = self.fixture()
        configure_product_copy_fixture(fixture)
        profile = fixture.scope["verification_resources"]["profiles"]["local"]
        # The first input is copied successfully; the second is a routine
        # missing declared dependency, so the partial copy must stay traceable.
        profile["product_copy"]["files"] = ["src/reader.py", "missing.py"]
        fixture.prepare()
        results, roots = [], []
        resource_root = Path(fixture.scope["verification_resources"]["root"])
        for _ in range(2):
            results.append(fixture.advance())
            roots.append(sorted(str(path) for path in resource_root.iterdir()))
        self.assertEqual([result["status"] for result in results],
                         ["HELD_COMMAND_FAILURE", "HELD_COMMAND_FAILURE"],
                         {"results": results, "resource_roots": roots})
        self.assertEqual(roots[0], roots[1], "a failed preparation cannot allocate another runtime copy")
        self.assertEqual(len(roots[0]), 1)
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
        planned = [row["payload"] for row in fixture.events("BUILD_COMMAND_PLANNED")
                   if row["payload"]["phase"] == "VERIFICATION"]
        observed = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(planned), 1)
        self.assertEqual(len(observed), 1)
        self.assertEqual(planned[0]["command_id"], observed[0]["command_id"])
        self.assertEqual([invocation["phase"] for invocation in fixture.runner.invocations], ["IMPLEMENTATION"])
        command = observed[0]
        outcome = command["result"]
        self.assertIs(outcome["workload_started"], False)
        self.assertIs(outcome["automatic_retry_allowed"], False)
        self.assertEqual(outcome["failure_domain"], "VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED")
        self.assertEqual(outcome["resource_cleanup"]["status"], "RETAINED")
        retained = Path(command["resource_binding"]["root"])
        self.assertEqual(str(retained), roots[0][0])
        self.assertEqual((retained / "product/src/reader.py").read_text(), support.GOOD_READER)
        self.assertFalse((retained / "product/missing.py").exists())
        observation = Path(command["observation_root"])
        durable = json.loads((observation / "result.json").read_text())
        self.assertIs(durable["workload_started"], False)
        self.assertFalse((observation / "started.json").exists())
        self.assertFalse((observation / "capture.json").exists(), "host preparation failure is not a subprocess capture")

    def test_same_workspace_temp_sqlite_and_bound_reports(self):
        fixture = self.fixture()
        checker = (fixture.verifier / "check.py").read_bytes()
        source = (fixture.source / "brief.md").read_bytes()
        fixture.prepare()
        with patch.dict(os.environ, {"FOUNDRY_FIXTURE_SECRET_NOT_AUTHORIZED": "do-not-forward"}):
            result = fixture.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        checks = [row for row in fixture.runner.invocations if row["phase"] == "VERIFICATION"]
        self.assertEqual(len(checks), 3)
        self.assertEqual(len({row["environment"]["FOUNDRY_SCRATCH_DIR"] for row in checks}), 3)
        for invocation in checks:
            self.assertEqual(invocation["cwd"], str(fixture.workspace))
            self.assertNotIn(str(fixture.workspace), invocation["write_roots"])
            self.assertEqual(invocation["environment"]["FOUNDRY_COMMAND_ID"], invocation["command_id"])
            self.assertEqual(invocation["environment"]["FOUNDRY_CASE_ID"], invocation["case_id"])
        self.assertEqual((fixture.source / "brief.md").read_bytes(), source)
        self.assertEqual((fixture.verifier / "check.py").read_bytes(), checker)
        self.assertEqual((fixture.workspace / "src/reader.py").read_text(), support.GOOD_READER)
        observed = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(observed), 3)
        for command in observed:
            self.assertIn("resource_binding", command)
            self.assertEqual(command["result"]["status"], "PASS")
            root = Path(command["observation_root"])
            self.assertTrue(any(path.name == "summary.json" for path in root.rglob("summary.json")),
                            "controller retains the bound report in protected host attachments")
        revision = len(fixture.events())
        readback = read_build(fixture.store.database_path, fixture.program)
        resources = [command for attempt in readback["attempts"] for command in attempt["resource_commands"]]
        self.assertEqual(len(resources), 3)
        for resource in resources:
            self.assertEqual(resource["effective_network_policy"]["mode"], "NONE")
            self.assertEqual(resource["cleanup"]["status"], "CLEANED")
            self.assertEqual([report["name"] for report in resource["reports"]], ["summary.json"])
            self.assertTrue(Path(resource["reports"][0]["path"]).is_file())
        self.assertEqual(len(fixture.events()), revision, "readback does not create additional execution records")

    def test_incomplete_wrong_identity_or_contradictory_report_never_repairs_product(self):
        for mode in ("missing", "stale", "wrong-case", "zero", "skipped", "error", "exit-contradiction"):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                fixture.prepare()
                result = fixture.advance()
                self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
                self.assertEqual(fixture.events("BUILD_ATTEMPT_FINISHED")[-1]["payload"]["status"], "BLOCKED")
                self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
                self.assertFalse(fixture.events("BUILD_ACCEPTANCE_INVALIDATED"))
                self.assertEqual(len([row for row in fixture.runner.invocations
                                      if row["phase"] == "IMPLEMENTATION"]), 1)
                observations = [row["payload"]["result"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                                if row["payload"]["phase"] == "VERIFICATION"]
                self.assertFalse(observations[-1]["automatic_retry_allowed"])

    def test_complete_business_assertion_retains_native_repair_classification(self):
        fixture = self.fixture("business-failure")
        fixture.prepare()
        result = fixture.controller().advance(fixture.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["status"], "BUILD_CONTROL_RETURNED", result)
        self.assertEqual(result["attempt_status"], "REJECTED")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
        observed = [row["payload"]["result"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertTrue(observed)
        self.assertTrue(all(row["automatic_retry_allowed"] for row in observed))

    def test_complete_report_cannot_turn_timed_out_process_into_acceptance(self):
        fixture = self.fixture("timeout-after-report")
        fixture.scope["command_timeout_seconds"] = 1
        fixture.prepare()
        result = fixture.advance()
        self.assertNotEqual(result["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(fixture.events("BUILD_ATTEMPT_FINISHED")[-1]["payload"]["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertFalse(fixture.events("BUILD_ACCEPTANCE_INVALIDATED"))

    def test_same_repo_checker_and_declared_helper_run_from_approved_snapshot(self):
        fixture = self.fixture()
        checker_source = fixture.workspace / "tests"
        checker_source.mkdir()
        helper_check = '\nassert json.loads(Path(__file__).with_name("helper.json").read_text()) == {"value": "approved"}\n'
        script = RESOURCE_CHECKER.replace('case, mode = sys.argv[1:3]', helper_check + 'case, mode = sys.argv[1:3]')
        (checker_source / "check.py").write_text(script)
        (checker_source / "helper.json").write_text('{"value":"approved"}')
        fixture.scope["verification_root"] = str(checker_source)
        fixture.scope["verification_resources"]["checker_files"] = ["helper.json"]
        fixture.prepare()
        # Product-side edits cannot silently replace the approved oracle/deps.
        (checker_source / "check.py").write_text('raise RuntimeError("unapproved changed checker")\n')
        (checker_source / "helper.json").write_text('{"value":"changed"}')
        result = fixture.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        checks = [row for row in fixture.runner.invocations if row["phase"] == "VERIFICATION"]
        self.assertEqual(len(checks), 3)
        for invocation in checks:
            checker_path = Path(invocation["argv"][3])
            self.assertFalse(checker_path.is_relative_to(fixture.workspace))
            self.assertEqual(checker_path.read_text(), script)
            self.assertEqual(json.loads(checker_path.with_name("helper.json").read_text()), {"value": "approved"})


    def check_protected_dependency_resolution(self, access, *, fixture_factory=None):
        for reader, expected_status in ((support.BAD_READER, "REJECTED"), (support.GOOD_READER, "ACCEPTED")):
            with self.subTest(access=access, product=expected_status):
                fixture = (fixture_factory or self.fixture)()
                source = configure_dependency_fixture(fixture, access, reader)
                fixture.prepare()
                change_product_oracle_files(source)
                result = fixture.controller().advance(fixture.prepared_id, advance_mode="ONE_ATTEMPT")
                self.assertEqual(result["attempt_status"], expected_status, result)
                commands = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                            if row["payload"]["phase"] == "VERIFICATION"]
                self.assertTrue(commands)
                for command in commands:
                    binding = command["resource_binding"]
                    root = Path(binding["verifier_root"])
                    self.assertFalse(root.is_relative_to(fixture.workspace))
                    self.assertEqual(binding["env"]["FOUNDRY_VERIFIER_ROOT"], str(root))
                    report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
                    self.assertEqual(report["expected"], {"rows": 3, "invalid": 2})
                    self.assertEqual(report["product_cwd"], str(fixture.workspace))
                    self.assertTrue(all(Path(path).is_relative_to(root) for path in report["oracle_files"]))
                    if expected_status == "REJECTED":
                        self.assertEqual(command["result"]["failure_domain"], "BUSINESS_ASSERTION")
                        self.assertTrue(command["result"]["automatic_retry_allowed"])
                if expected_status == "ACCEPTED":
                    self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")

    def test_bound_context_oracle_rejects_wrong_product_despite_changed_source_expectation(self):
        self.check_protected_dependency_resolution("context")

    def test_explicit_verifier_argument_rejects_wrong_product_despite_changed_source_expectation(self):
        self.check_protected_dependency_resolution("argument")

    def check_completed_resource_recovery(self, mode):
        fixture = self.fixture(mode)
        fixture.prepare()
        controller = fixture.controller()
        crashed_command = []

        def crash_after_first_check(invocation, result):
            if invocation["phase"] == "VERIFICATION" and not crashed_command:
                crashed_command.append(invocation["command_id"])
                raise support.InjectedControllerCrash()

        fixture.runner.after_run = crash_after_first_check
        with self.assertRaises(support.InjectedControllerCrash):
            controller.advance(fixture.prepared_id)
        fixture.runner.after_run = None
        result = controller.advance(fixture.prepared_id)
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(fixture.runner.invocations), 5, "no implementation or completed check redispatch")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 2)
        recovered = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                     if row["payload"]["command_id"] == crashed_command[0]]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["result"]["status"], "PASS")
        self.assertIn("resource_binding", recovered[0])
        self.assertEqual(recovered[0]["resource_binding"]["verifier_root"],
                         recovered[0]["resource_binding"]["env"]["FOUNDRY_VERIFIER_ROOT"])
        if mode == "local-tcp":
            self.assertEqual(recovered[0]["result"]["network"], "LOCAL_SERVICE")
            self.check_tcp_observation(recovered[0], fixture.workspace)
            human = render_build_readback(read_build(fixture.store.database_path, fixture.program))
            for boundary in ("LOOPBACK", "TCP/UDP", "回环全部端口", "53 端口例外", "不隔离其他本机服务"):
                self.assertIn(boundary, human)
        else:
            self.assertEqual(recovered[0]["result"]["network"], "DENY")
            self.assertEqual(recovered[0]["result"]["effective_network_policy"]["mode"], "NONE")
        revisions = len(fixture.events())
        self.assertEqual(controller.advance(fixture.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(fixture.events()), revisions)
        self.assertEqual(len(fixture.runner.invocations), 5)

    def test_completed_resource_capture_recovers_without_redispatch_or_double_budget(self):
        self.check_completed_resource_recovery("pass")

    def test_local_tcp_capture_recovers_without_restarting_service_or_double_budget(self):
        self.check_completed_resource_recovery("local-tcp")

    def check_tcp_observation(self, command, workspace):
        outcome = command["result"]
        self.assertEqual(command["resource_binding"]["network"], {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"})
        self.assertEqual(outcome["effective_network_policy"]["mode"], "LOCAL_SERVICE")
        self.assertEqual(outcome["effective_network_policy"]["tcp"], "LOOPBACK")
        self.assertEqual(outcome["effective_network_policy"]["loopback_protocols"], ["TCP", "UDP"])
        self.assertEqual(outcome["effective_network_policy"]["external_network"], "DENY_EXCEPT_NATIVE_DNS_PORT_53")
        self.assertEqual(outcome["effective_network_policy"]["guarantee"], "LOOPBACK_ALL_PORTS_NOT_SERVICE_ISOLATION")
        report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
        self.assertEqual(report["service_endpoint"]["host"], "127.0.0.1")
        self.assertGreater(report["service_endpoint"]["port"], 0)
        self.assertLessEqual(report["service_endpoint"]["port"], 65535)
        self.assertEqual(report["product_cwd"], str(workspace))
        self.assertIs(report["services_stopped"], True)
        self.assertEqual(outcome["resource_cleanup"]["status"], "CLEANED")
        for area in command["resource_binding"]["areas"].values():
            self.assertFalse(Path(area).exists())

    def check_tcp_start_failure(self, *, fixture_factory=None):
        fixture = (fixture_factory or self.fixture)("local-tcp-start-failure")
        fixture.prepare()
        result = fixture.advance()
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertFalse(fixture.events("BUILD_ACCEPTANCE_INVALIDATED"))
        self.assertEqual(fixture.events("BUILD_ATTEMPT_FINISHED")[-1]["payload"]["status"], "BLOCKED")
        observed = [row["payload"] for row in fixture.events("BUILD_COMMAND_OBSERVED")
                    if row["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(observed), 1)
        outcome = observed[0]["result"]
        self.assertFalse(outcome["automatic_retry_allowed"])
        self.assertEqual(outcome["failure_domain"], "VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED")
        report = json.loads((Path(observed[0]["observation_root"]) / "reports/summary.json").read_text())
        self.assertEqual(report["checks"][-1], {"id": "service", "status": "ERROR"})
        self.assertIn("OWNED_SERVICE_START_FAILED", report["errors"][0])
        self.assertIs(report["services_stopped"], True)
        self.assertEqual(report["product_cwd"], str(fixture.workspace))
        self.assertTrue(Path(observed[0]["resource_binding"]["areas"]["scratch"]).exists())

    def test_local_tcp_start_failure_does_not_use_existing_listener_or_repair_product(self):
        self.check_tcp_start_failure()

    def test_resource_prepare_retry_reuses_snapshot_and_changed_request_conflicts(self):
        fixture = self.fixture()
        fixture.prepare(approve=False)
        snapshots = list(fixture.root.glob("controller.verifiers/VERIFIER-*"))
        self.assertEqual(len(snapshots), 1)
        prepared = fixture.events("BUILD_AUTHORIZATION_PREPARED")[0]
        request = dict(expected_revision=prepared["stream_revision"] - 1,
                       idempotency_key="prepare", created_at=support.NOW)
        replay = prepare_build_authorization(fixture.store, fixture.program, fixture.proposal_id,
                                            fixture.source_id, fixture.scope, **request)
        self.assertEqual(replay["event_id"], prepared["event_id"])
        self.assertEqual(list(fixture.root.glob("controller.verifiers/VERIFIER-*")), snapshots)
        self.assertEqual(len(fixture.events("BUILD_AUTHORIZATION_PREPARED")), 1)
        changed = deepcopy(fixture.scope)
        changed["verification_resources"]["profiles"]["local"]["required_checks"].append("another")
        with self.assertRaises(IdempotencyConflictError):
            prepare_build_authorization(fixture.store, fixture.program, fixture.proposal_id,
                                        fixture.source_id, changed, **request)
        self.assertEqual(list(fixture.root.glob("controller.verifiers/VERIFIER-*")), snapshots)

    def test_replan_preserves_resource_reference_and_rejects_profile_substitution(self):
        fixture = self.fixture()
        fixture.scope["verification_resources"]["profiles"]["other"] = deepcopy(
            fixture.scope["verification_resources"]["profiles"]["local"])
        original = deepcopy(fixture.plan)
        revised = deepcopy(original)
        revised["revision"] += 1
        revised["workpacks"][0]["goal"] = "Use a different reader implementation."
        writes, _ = adapt_build_plan(original, revised, fixture.scope)
        self.assertEqual(writes, fixture.scope["task_write_roots"])
        revised["workpacks"][0]["verification"][0]["resource_profile_ref"] = "other"
        with self.assertRaisesRegex(RequestValidationError, "acceptance"):
            adapt_build_plan(original, revised, fixture.scope)


if __name__ == "__main__":
    unittest.main()
