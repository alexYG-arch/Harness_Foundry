"""Consume the shipped resource example, using synthetic local test authority.

The ordinary runner exercises real Python processes but does not qualify an OS
sandbox. The opt-in class repeats the example through the native receiver.
"""

from copy import deepcopy
import errno
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_runtime import (
    NativeBuildRunner, prepare_build_authorization, record_source_snapshot,
)
from harness_foundry_factory.resource_observation import finish_resource_observation
from tests.build_review_fixture import reviewed_document
import test_build_resources as resource_support
import test_build_runtime as support


EXAMPLE = Path(__file__).resolve().parents[1] / "examples/resource-check"


PARALLEL_PYTEST_WORKER = r'''import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time


def test_worker_resources(tmp_path, tmp_path_factory, request):
    worker = os.environ["FOUNDRY_PYTEST_WORKER"]
    scratch = Path(os.environ["FOUNDRY_SCRATCH_DIR"])
    base = scratch / ("pytest-worker-" + worker)
    assert tmp_path_factory.getbasetemp() == base
    assert tmp_path.is_relative_to(base)
    assert Path(tempfile.gettempdir()) == scratch
    (tmp_path / "same.txt").write_text(worker)
    request.config.cache.set("worker/identity", worker)
    db = sqlite3.connect(tmp_path / "same.sqlite3")
    started = time.monotonic_ns()
    try:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        db.execute("CREATE TABLE owner (id TEXT)")
        db.execute("INSERT INTO owner VALUES (?)", (worker,))
        db.commit()
        assert (tmp_path / "same.sqlite3-wal").exists()
        assert (tmp_path / "same.sqlite3-shm").exists()
        (scratch / ("ready-" + worker)).write_text("ready")
        deadline = time.monotonic() + 10
        while not all((scratch / ("ready-" + peer)).exists() for peer in ("0", "1")):
            if time.monotonic() > deadline:
                raise AssertionError("pytest workers did not overlap")
            time.sleep(0.01)
        assert (tmp_path / "same.txt").read_text() == worker
        assert db.execute("SELECT id FROM owner").fetchall() == [(worker,)]
        assert request.config.cache.get("worker/identity", None) == worker
    finally:
        db.close()
    with tempfile.TemporaryDirectory(prefix="worker-" + worker + "-") as temporary:
        assert Path(temporary).is_relative_to(scratch)
    assert not Path(temporary).exists()
    report = {"worker": worker, "pid": os.getpid(), "started_ns": started,
              "finished_ns": time.monotonic_ns(), "base": str(base),
              "tmp_path": str(tmp_path), "cache": str(request.config.cache._cachedir)}
    Path(os.environ["FOUNDRY_REPORT_DIR"], "worker-" + worker + ".json").write_text(json.dumps(report))
'''

PARALLEL_PYTEST_CHECKER = r'''import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


verifier = Path(os.environ["FOUNDRY_VERIFIER_ROOT"])
scratch = Path(os.environ["FOUNDRY_SCRATCH_DIR"])
product = Path(os.environ["FOUNDRY_PRODUCT_ROOT"])
reports = Path(os.environ["FOUNDRY_REPORT_DIR"])
children = []
try:
    for worker in ("0", "1"):
        environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                       "FOUNDRY_PYTEST_WORKER": worker}
        command = [sys.argv[3], "-I", "-B", "-m", "pytest", "-q", "-c", str(verifier / "pytest.ini"),
                   "--rootdir", str(verifier), "--confcutdir", str(verifier),
                   "--basetemp", str(scratch / ("pytest-worker-" + worker)),
                   "-o", "cache_dir=" + str(product / ".cache" / ("worker-" + worker)),
                   str(verifier / "test_parallel_worker.py")]
        children.append(subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True))
    for child in children:
        output, _ = child.communicate(timeout=20)
        print(output, end="", file=sys.stderr)
        if child.returncode != 0:
            raise RuntimeError("parallel pytest worker failed")
finally:
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
workers = [json.loads((reports / ("worker-" + worker + ".json")).read_text()) for worker in ("0", "1")]
if max(row["started_ns"] for row in workers) >= min(row["finished_ns"] for row in workers):
    raise RuntimeError("workers were not concurrently active")
if len({row["pid"] for row in workers}) != 2:
    raise RuntimeError("workers did not use separate processes")
for worker in ("0", "1"):
    if json.loads((product / ".cache" / ("worker-" + worker) / "v/worker/identity").read_text()) != worker:
        raise RuntimeError("worker cache was overwritten")
spec = importlib.util.spec_from_file_location("protected_check", verifier / "check_resources.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
status = module.run_checks(sys.argv[1], sys.argv[2])
summary = json.loads((reports / "summary.json").read_text())
summary["checks"].append({"id": "workers", "status": "PASS"})
summary["tests_run"] += len(workers)
summary["parallel_workers"] = workers
(reports / "summary.json").write_text(json.dumps(summary))
raise SystemExit(status)
'''


def example_fixture(owner, mode="offline", *, example_root=EXAMPLE, native=False):
    """Reuse the existing controller fixture, replacing its data with the example."""
    fixture = support.BuildRuntimeTests()
    fixture.setUp()
    owner.addCleanup(fixture.doCleanups)
    shutil.copytree(example_root / "starter", fixture.workspace, dirs_exist_ok=True)
    shutil.copytree(example_root / "verifier", fixture.verifier, dirs_exist_ok=True)
    shutil.copy2(example_root / "PROJECT_BRIEF.md", fixture.source / "PROJECT_BRIEF.md")
    fixture.request = json.loads((example_root / "request.template.json").read_text())
    fixture.ir, fixture.plan = fixture.request["requirement_ir"], fixture.request["plan"]
    fixture.program = fixture.ir["program_id"]
    fixture.review = reviewed_document(fixture.source, path=fixture.source / "PROJECT_BRIEF.md")
    fixture.request["document_review"] = fixture.review
    fixture.scope = json.loads((example_root / "scope.template.json").read_text())
    fixture.scope.update(workspace_root=str(fixture.workspace), verification_root=str(fixture.verifier),
                         source_read_roots=[sys.prefix, sys.base_prefix],
                         executables={"python": sys.executable}, codex_executable="/usr/bin/true",
                         expires_at="2026-09-18T01:00:00Z")
    resource_root = fixture.root / "resource-runs"
    resource_root.mkdir()
    fixture.scope["verification_resources"]["root"] = str(resource_root)
    if mode == "tcp":
        profiles = fixture.scope["verification_resources"]["profiles"]
        profile = profiles.pop("offline")
        profile["network"] = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"}
        profile["required_checks"].append("service")
        profiles["local-tcp"] = profile
        for task in fixture.plan["workpacks"]:
            for check in task["verification"]:
                check["resource_profile_ref"] = "local-tcp"
                check["argv"][-1] = "tcp"
    fixture.runner = resource_support.DurableResourceFixtureRunner()
    if native:
        fixture.scope["codex_executable"] = os.environ["HFFACTORY_TEST_CODEX_SANDBOX"]
        fixture.scope["source_read_roots"] += [str(Path(sys._base_executable).parent),
            *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]
        fixture.runner = NativeBuildRunner()
    return fixture



def configure_parallel_pytest(fixture):
    """Use an explicitly selected existing pytest environment; never install."""
    executable = os.environ["HFFACTORY_TEST_PYTEST_PYTHON"]
    probe = subprocess.run([executable, "-I", "-B", "-c",
        "import json,sys,pytest; print(json.dumps([sys.prefix,sys.base_prefix]))"],
        check=True, capture_output=True, text=True, timeout=10)
    fixture.scope["executables"]["pytest-python"] = executable
    fixture.scope["source_read_roots"] += json.loads(probe.stdout)
    fixture.scope["source_read_roots"].append(str(Path(executable).resolve().parent))
    resources = fixture.scope["verification_resources"]
    resources["checker_files"] += ["check_resources.py", "test_parallel_worker.py", "pytest.ini"]
    profile = next(iter(resources["profiles"].values()))
    profile["required_checks"].append("workers")
    profile["report_files"] += ["worker-0.json", "worker-1.json"]
    (fixture.verifier / "pytest.ini").write_text("[pytest]\n")
    (fixture.verifier / "test_parallel_worker.py").write_text(PARALLEL_PYTEST_WORKER)
    (fixture.verifier / "parallel_pytest.py").write_text(PARALLEL_PYTEST_CHECKER)
    for task in fixture.plan["workpacks"]:
        for check in task["verification"]:
            check["argv"][3] = "verifier://parallel_pytest.py"
            check["argv"].append("executable://pytest-python")


def prepare_example(fixture, *, approve=True):
    proposal = record_build_plan_proposal(fixture.store, fixture.ir, fixture.plan,
        document_review=fixture.review, **fixture.kwargs("proposal"))
    fixture.proposal_id = proposal["event_id"]
    source = record_source_snapshot(fixture.store, fixture.program, fixture.proposal_id, fixture.source,
        [{"source_id": "PROJECT-BRIEF", "path": "PROJECT_BRIEF.md"}], **fixture.kwargs("sources"))
    fixture.source_id = source["event_id"]
    prepared = prepare_build_authorization(fixture.store, fixture.program, fixture.proposal_id,
        fixture.source_id, fixture.scope, **fixture.kwargs("prepare"))
    fixture.prepared_id = prepared["event_id"]
    if approve:
        fixture.approve()
    return prepared


def verification_commands(fixture):
    return [event["payload"] for event in fixture.events("BUILD_COMMAND_OBSERVED")
            if event["payload"]["phase"] == "VERIFICATION"]


class ResourceExampleTests(unittest.TestCase):
    def test_templates_compile_prepare_and_readback_without_execution(self):
        fixture = example_fixture(self)
        compiled = compile_build_plan(fixture.ir, fixture.plan)
        self.assertEqual(compiled["status"], "PLAN_COMPILED_NOT_AUTHORIZED")
        self.assertFalse(compiled["execution_started"])
        prepared = prepare_example(fixture, approve=False)
        view = read_build(fixture.store.database_path, fixture.program)
        scope = view["authorizations"][0]["scope"]
        self.assertEqual(scope, prepared["payload"]["scope"])
        self.assertEqual(set(scope["verification_resources"]["profiles"]), {"offline"})
        self.assertEqual(scope["verification_resources"]["profiles"]["offline"]["network"], {"mode": "NONE"})
        self.assertEqual(scope["verification_resources"]["checker_files"], ["expected.json"])
        self.assertFalse(scope["allow_model_service"])
        self.assertEqual(view["attempts"], [])
        self.assertFalse((fixture.workspace / "outputs/summary.json").exists())
        self.assertEqual(fixture.runner.invocations, [])

    def assert_success(self, fixture, *, mode="offline", native=False):
        self.assertEqual(json.loads((fixture.workspace / "outputs/summary.json").read_text()),
                         {"rows": 4, "total": 12, "invalid": 1})
        commands = verification_commands(fixture)
        self.assertEqual(len(commands), 1)
        command = commands[0]
        binding, outcome = command["resource_binding"], command["result"]
        self.assertEqual(outcome["status"], "PASS", outcome)
        self.assertEqual(outcome["product_copy_validation"]["status"], "UNCHANGED")
        self.assertEqual(outcome["resource_cleanup"]["status"], "CLEANED")
        self.assertFalse(Path(binding["product_copy"]["root"]).exists())
        for area in binding["areas"].values():
            self.assertFalse(Path(area).exists())
        report_path = Path(command["observation_root"]) / "reports/summary.json"
        report = json.loads(report_path.read_text())
        expected_checks = {"product", "temp", "sqlite"} | ({"service"} if mode == "tcp" else set())
        if "parallel_workers" in report:
            expected_checks.add("workers")
            workers = report["parallel_workers"]
            self.assertEqual({row["worker"] for row in workers}, {"0", "1"})
            self.assertEqual(len({row["pid"] for row in workers}), 2)
            self.assertLess(max(row["started_ns"] for row in workers),
                            min(row["finished_ns"] for row in workers))
            for row in workers:
                self.assertEqual(Path(row["base"]),
                                 Path(binding["areas"]["scratch"]) / ("pytest-worker-" + row["worker"]))
                self.assertTrue(Path(row["tmp_path"]).is_relative_to(Path(row["base"])))
                self.assertEqual(Path(row["cache"]),
                                 Path(binding["product_copy"]["root"]) / ".cache" / ("worker-" + row["worker"]))
                worker_report = Path(command["observation_root"]) / "reports" / ("worker-" + row["worker"] + ".json")
                self.assertEqual(json.loads(worker_report.read_text()), row)
            self.assertEqual(report["tests_run"], len(expected_checks) + 1)
        self.assertEqual({row["id"] for row in report["checks"]}, expected_checks)
        self.assertTrue(all(row["status"] == "PASS" for row in report["checks"]))
        self.assertEqual(report["command_id"], command["command_id"])
        self.assertEqual(report["case_id"], command["case_id"])
        self.assertEqual(report["product_cwd"], binding["product_copy"]["root"])
        self.assertEqual(report["verifier_root"], binding["verifier_root"])
        self.assertNotEqual(report["verifier_root"], str(fixture.verifier))
        self.assertFalse((fixture.workspace / ".cache").exists())
        self.assertFalse((fixture.workspace / "build").exists())
        if mode == "tcp":
            self.assertTrue(report["services_stopped"])
            endpoint = report["service_endpoint"]
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(1)
                self.assertEqual(probe.connect_ex((endpoint["host"], endpoint["port"])), errno.ECONNREFUSED,
                                    "the example must release its owned service listener")
        if native:
            self.assertEqual(outcome["receiver"], "CODEX_SANDBOX_PERMISSION_PROFILE")
        view = read_build(fixture.store.database_path, fixture.program)
        self.assertEqual(len(view["attempts"]), 1)
        self.assertEqual(len(view["attempts"][0]["resource_commands"]), 1)
        return report_path.read_bytes()

    def check_roundtrip(self, mode="offline", *, native=False):
        fixture = example_fixture(self, mode, native=native)
        original = (fixture.workspace / "tools/summarize.py").read_bytes()
        prepare_example(fixture)
        self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assert_success(fixture, mode=mode, native=native)
        self.assertEqual((fixture.workspace / "tools/summarize.py").read_bytes(), original)
        revision = len(fixture.events())
        self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(fixture.events()), revision)

    def test_shipped_offline_example_temp_sqlite_copy_and_cleanup(self):
        self.check_roundtrip()

    def test_shipped_loopback_example_service_and_cleanup(self):
        self.check_roundtrip("tcp")

    def check_wrong_product(self, *, native=False):
        fixture = example_fixture(self, native=native)
        (fixture.workspace / "fixtures/rows.json").write_text('{"values":[30,4,"invalid",5]}')
        prepare_example(fixture)
        # Changing the mutable source oracle cannot change the prepared checker.
        (fixture.verifier / "expected.json").write_text('{"rows":4,"total":39,"invalid":1}')
        result = fixture.controller().advance(fixture.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["attempt_status"], "REJECTED", result)
        command = verification_commands(fixture)[0]
        self.assertEqual(command["result"]["failure_domain"], "BUSINESS_ASSERTION")
        self.assertTrue(command["result"]["automatic_retry_allowed"])
        self.assertTrue(Path(command["resource_binding"]["product_copy"]["root"]).is_dir())
        report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
        self.assertEqual(report["failure_kind"], "ASSERTION")
        self.assertEqual(next(row["status"] for row in report["checks"] if row["id"] == "product"), "FAIL")

    def test_wrong_product_uses_protected_expectation_and_retains_repairable_evidence(self):
        self.check_wrong_product()

    def check_process_error(self, *, native=False):
        fixture = example_fixture(self, native=native)
        script = fixture.workspace / "tools/summarize.py"
        script.write_text("import sys\nif '--cache' in sys.argv:\n    raise RuntimeError('synthetic execution failure')\n" + script.read_text())
        prepare_example(fixture)
        calls = []
        original_runner = fixture.runner

        def runner(invocation, before_dispatch):
            calls.append(invocation["command_id"])
            return original_runner(invocation, before_dispatch)

        fixture.runner = runner
        result = fixture.advance()
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        command = verification_commands(fixture)[0]
        self.assertFalse(command["result"]["automatic_retry_allowed"])
        self.assertNotEqual(command["result"].get("failure_domain"), "BUSINESS_ASSERTION")
        self.assertTrue(Path(command["resource_binding"]["product_copy"]["root"]).is_dir())
        report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
        self.assertEqual(next(row["status"] for row in report["checks"] if row["id"] == "product"), "ERROR")
        count = len(calls)
        self.assertEqual(fixture.advance()["status"], "HELD_COMMAND_FAILURE")
        self.assertEqual(len(calls), count)
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)

    def test_product_process_error_is_not_business_assertion_or_automatic_repair(self):
        self.check_process_error()

    def test_resource_assertion_is_not_misclassified_as_product_failure(self):
        fixture = example_fixture(self)
        original_runner = fixture.runner

        def wrong_temporary_environment(invocation, before_dispatch):
            if invocation["phase"] == "VERIFICATION":
                invocation = {**invocation, "environment": {**invocation["environment"],
                    "TMPDIR": invocation["resource_binding"]["areas"]["report-staging"]}}
            return original_runner(invocation, before_dispatch)

        fixture.runner = wrong_temporary_environment
        prepare_example(fixture)
        result = fixture.advance()
        self.assertEqual(result["status"], "HELD_COMMAND_FAILURE", result)
        command = verification_commands(fixture)[0]
        self.assertFalse(command["result"]["automatic_retry_allowed"])
        self.assertNotEqual(command["result"].get("failure_domain"), "BUSINESS_ASSERTION")
        report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
        statuses = {row["id"]: row["status"] for row in report["checks"]}
        self.assertEqual(statuses["product"], "PASS")
        self.assertEqual(statuses["temp"], "ERROR")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)

    def check_recovery(self, *, after_cleanup=False, mode="offline", native=False, parallel_pytest=False):
        fixture = example_fixture(self, mode, native=native)
        if parallel_pytest:
            configure_parallel_pytest(fixture)
        prepare_example(fixture)
        original_runner = fixture.runner
        calls, interrupted = [], []

        def runner(invocation, before_dispatch):
            calls.append({key: deepcopy(value) for key, value in invocation.items() if not callable(value)})
            result = original_runner(invocation, before_dispatch)
            if invocation["phase"] == "VERIFICATION" and not after_cleanup and not interrupted:
                interrupted.append(invocation["command_id"])
                raise support.InjectedControllerCrash()
            return result

        def finish_then_interrupt(raw, binding, root):
            result = finish_resource_observation(raw, binding, root)
            if after_cleanup and not interrupted:
                self.assertEqual(result["status"], "PASS", result)
                self.assertFalse(Path(binding["product_copy"]["root"]).exists())
                interrupted.append(binding["command_id"])
                raise support.InjectedControllerCrash()
            return result

        fixture.runner = runner
        with patch("harness_foundry_factory.build_resource_lifecycle.finish_resource_observation", side_effect=finish_then_interrupt):
            with self.assertRaises(support.InjectedControllerCrash):
                fixture.advance()
        self.assertEqual(len(calls), 2)
        with patch("harness_foundry_factory.build_resource_lifecycle.materialize_product_copy",
                   side_effect=AssertionError("recovery must not recopy a completed example command")):
            self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(calls), 2, "neither the product command nor completed check is replayed")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(len([row for row in verification_commands(fixture)
                              if row["command_id"] == interrupted[0]]), 1)
        evidence = self.assert_success(fixture, mode=mode, native=native)
        revision = len(fixture.events())
        self.assertEqual(fixture.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(fixture.events()), revision)
        self.assertEqual(self.assert_success(fixture, mode=mode, native=native), evidence)
        self.assertEqual(len(calls), 2)

    def test_capture_recovery_does_not_repeat_example_or_budget(self):
        self.check_recovery()

    def test_durable_cleanup_recovery_does_not_recreate_copy_or_service(self):
        self.check_recovery(after_cleanup=True, mode="tcp")


@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "native receiver opt-in required")
class NativeResourceExampleTests(unittest.TestCase):
    def holder(self):
        holder = ResourceExampleTests()
        self.addCleanup(holder.doCleanups)
        return holder

    def test_native_shipped_offline_example_capture_recovery(self):
        self.holder().check_recovery(native=True)

    def test_native_shipped_loopback_example_cleaned_recovery(self):
        self.holder().check_recovery(after_cleanup=True, mode="tcp", native=True)

    def test_native_shipped_wrong_product_uses_protected_expectation(self):
        self.holder().check_wrong_product(native=True)

    def test_native_shipped_execution_error_is_held_without_repair(self):
        self.holder().check_process_error(native=True)



@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_PYTEST_PYTHON"), "existing pytest interpreter opt-in required")
class ParallelPytestResourceTests(unittest.TestCase):
    def holder(self):
        holder = ResourceExampleTests()
        self.addCleanup(holder.doCleanups)
        return holder

    def test_parallel_pytest_basetemp_cache_sqlite_capture_recovery(self):
        self.holder().check_recovery(parallel_pytest=True)

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "native receiver opt-in required")
    def test_native_parallel_pytest_basetemp_cache_sqlite_and_http_cleanup_recovery(self):
        self.holder().check_recovery(parallel_pytest=True, after_cleanup=True, mode="tcp", native=True)


if __name__ == "__main__":
    unittest.main()
