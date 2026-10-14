"""Unittest adapter for Foundry STRUCTURED_V1; no runner or authority store."""

import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest


class CheckResult(unittest.TextTestResult):
    """Keep assertion failures separate from execution/discovery errors."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checks = []

    def record(self, test, status):
        self.checks.append({"id": getattr(test, "_testMethodName", str(test)).removeprefix("test_"),
                            "status": status})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "PASS")

    def addFailure(self, test, err):
        if getattr(test, "_testMethodName", None) != "test_product":
            # Resource availability/cleanup assertions are not a reason to
            # repair the summary product. Keep the original unittest traceback.
            super().addError(test, err)
            self.record(test, "ERROR")
            return
        super().addFailure(test, err)
        self.record(test, "FAIL")

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "ERROR")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "SKIP")


def run_checks(python_executable, mode):
    product = Path(os.environ["FOUNDRY_PRODUCT_ROOT"])
    verifier = Path(os.environ["FOUNDRY_VERIFIER_ROOT"])
    scratch = Path(os.environ["FOUNDRY_SCRATCH_DIR"])
    service_state = {"service_endpoint": None, "services_stopped": True}

    class ResourceChecks(unittest.TestCase):
        def test_product(self):
            if Path.cwd() != product or not Path(__file__).resolve().is_relative_to(verifier):
                raise RuntimeError("checker/product context is not bound to the protected run")
            expected = json.loads((verifier / "expected.json").read_text(encoding="utf-8"))
            if Path("build/summary.json").exists():
                raise RuntimeError("generated output already exists before the product check")
            subprocess.run([python_executable, "-I", "-B", "tools/summarize.py",
                            "--output", "build/summary.json", "--cache", ".cache/last-run.json"],
                           check=True, timeout=5)
            self.assertEqual(json.loads(Path("build/summary.json").read_text()), expected)
            self.assertEqual(json.loads(Path("outputs/summary.json").read_text()), expected)
            self.assertEqual(json.loads(Path(".cache/last-run.json").read_text())["result"], expected)
            boolean_input = scratch / "boolean.json"
            boolean_input.write_text('{"values": [true, 1]}', encoding="utf-8")
            subprocess.run([python_executable, "-I", "-B", "tools/summarize.py",
                            "--input", str(boolean_input), "--output", "build/boolean.json"],
                           check=True, timeout=5)
            self.assertEqual(json.loads(Path("build/boolean.json").read_text()),
                             {"rows": 2, "total": 1, "invalid": 1})
            for label, data in (("null-values", '{"values": null}'), ("non-object", '[]')):
                malformed = scratch / (label + ".json")
                malformed.write_text(data, encoding="utf-8")
                output = "build/" + label + ".json"
                invalid = subprocess.run([python_executable, "-I", "-B", "tools/summarize.py",
                                          "--input", str(malformed), "--output", output],
                                         capture_output=True, text=True, timeout=5)
                self.assertEqual(invalid.returncode, 2)
                self.assertIn("INVALID_INPUT", invalid.stderr)
                self.assertFalse(Path(output).exists())

        def test_temp(self):
            self.assertEqual(Path(tempfile.gettempdir()), scratch)
            with tempfile.TemporaryDirectory() as temporary:
                self.assertTrue(Path(temporary).is_relative_to(scratch))
                path = Path(temporary) / "sample.txt"
                path.write_text("temporary input", encoding="utf-8")
                self.assertEqual(path.read_text(), "temporary input")
            self.assertFalse(Path(temporary).exists())

        def test_sqlite(self):
            path = scratch / "example.sqlite3"
            database = sqlite3.connect(path)
            try:
                self.assertEqual(database.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                database.execute("CREATE TABLE records (value TEXT)")
                database.execute("INSERT INTO records VALUES ('committed')")
                database.commit()
                self.assertTrue(path.with_name(path.name + "-wal").exists())
                self.assertTrue(path.with_name(path.name + "-shm").exists())
                database.execute("INSERT INTO records VALUES ('rolled back')")
                database.rollback()
                database.execute("ALTER TABLE records ADD COLUMN revision INTEGER DEFAULT 1")
                database.commit()
            finally:
                database.close()
            reopened = sqlite3.connect(path)
            try:
                self.assertEqual(reopened.execute("SELECT value, revision FROM records").fetchall(),
                                 [("committed", 1)])
            finally:
                reopened.close()

        def test_service(self):
            identity = os.environ["FOUNDRY_COMMAND_ID"].encode("utf-8")

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(identity)))
                    self.end_headers()
                    self.wfile.write(identity)

                def log_message(self, *args):
                    pass

            # Bind once. Never discover a free port, close it, then race to rebind.
            service = HTTPServer(("127.0.0.1", 0), Handler)
            host, port = service.server_address
            service_state.update(service_endpoint={"host": host, "port": port}, services_stopped=False)
            thread = threading.Thread(target=service.serve_forever, kwargs={"poll_interval": 0.05})
            client = http.client.HTTPConnection(host, port, timeout=3)
            started = False
            try:
                thread.start()
                started = True
                client.request("GET", "/ready")
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), identity)
            finally:
                client.close()
                if started:
                    service.shutdown()
                service.server_close()
                if started:
                    thread.join(timeout=3)
                    if thread.is_alive():
                        raise RuntimeError("owned HTTP service did not stop")
                service_state["services_stopped"] = True

    names = ["product", "temp", "sqlite"] + (["service"] if mode == "tcp" else [])
    suite = unittest.TestSuite(ResourceChecks("test_" + name) for name in names)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2, resultclass=CheckResult).run(suite)
    errors = [text for _test, text in result.errors]
    complete = result.testsRun == len(names) and not result.skipped
    passed = complete and result.wasSuccessful()
    report = {"schema_version": "1.0", "case_id": os.environ["FOUNDRY_CASE_ID"],
              "command_id": os.environ["FOUNDRY_COMMAND_ID"],
              "status": "CHECKS_PASS" if passed else "CHECKS_FAILED",
              "checks": result.checks, "errors": errors, "tests_run": result.testsRun,
              "skipped": [str(test) for test, _reason in result.skipped],
              "product_cwd": str(product), "verifier_root": str(verifier), **service_state}
    if result.failures and not errors and complete:
        report["failure_kind"] = "ASSERTION"
    Path(os.environ["FOUNDRY_REPORT_DIR"], "summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in {"offline", "tcp"}:
        raise SystemExit("usage: check_resources.py ABSOLUTE_PYTHON offline|tcp")
    raise SystemExit(run_checks(sys.argv[1], sys.argv[2]))
