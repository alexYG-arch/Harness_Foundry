"""Opt-in native controller-to-checker resource execution, never a model call."""

from copy import deepcopy
import json
import os
from pathlib import Path
import ssl
import sys
import unittest

from harness_foundry_factory.build_runtime import NativeBuildRunner
import test_build_resources as resource_support
import test_build_runtime as support


@unittest.skipUnless(os.environ.get("HFFACTORY_TEST_CODEX_SANDBOX"), "native receiver opt-in required")
class NativeBuildResourceTests(unittest.TestCase):
    def fixture(self, mode):
        holder = resource_support.BuildResourceIntegrationTests()
        self.addCleanup(holder.doCleanups)
        fixture = holder.fixture(mode)
        fixture.scope["codex_executable"] = os.environ["HFFACTORY_TEST_CODEX_SANDBOX"]
        fixture.scope["command_timeout_seconds"] = 30
        fixture.scope["source_read_roots"] += [str(Path(sys._base_executable).parent),
            *json.loads(os.environ.get("HFFACTORY_TEST_PYTHON_READ_ROOTS", "[]"))]
        # HTTPS needs the selected interpreter's existing trust store, which may
        # live outside its library installation (for example Homebrew's etc/).
        trust = ssl.get_default_verify_paths()
        trust_paths = [value for value in (trust.cafile, trust.capath) if value and Path(value).exists()]
        if trust.cafile:
            # The default CA name can be a symlink: permit its configuration
            # directory as well as the resolved CA file, without disabling TLS.
            trust_paths.append(str(Path(trust.cafile).parent))
        fixture.scope["source_read_roots"] += trust_paths
        return fixture

    def check_recovery(self, mode):
        fixture = self.fixture(mode)
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
        try:
            early_result = fixture.advance()
        except support.InjectedControllerCrash:
            pass
        else:
            self.fail(f"first verification was not dispatched: {early_result!r}; captures={captures!r}")
        self.assertEqual(captures[-1]["status"], "PASS", captures[-1])
        result = fixture.advance()
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(len(invocations), 5, "recovery must not repeat an implementation or completed service call")
        self.assertEqual(len(fixture.events("BUILD_ATTEMPT_STARTED")), 2)
        checks = [row for row in fixture.events("BUILD_COMMAND_OBSERVED") if row["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(checks), 3)
        expected_mode = {"local-service": "LOCAL_SERVICE", "local-tcp": "LOCAL_SERVICE",
                         "remote-service": "REMOTE_SERVICE"}[mode]
        for event in checks:
            command, outcome = event["payload"], event["payload"]["result"]
            self.assertEqual(outcome["status"], "PASS", outcome)
            self.assertEqual(outcome["network"], expected_mode)
            self.assertEqual(outcome["effective_network_policy"]["mode"], expected_mode)
            report = json.loads((Path(command["observation_root"]) / "reports" / "summary.json").read_text())
            self.assertEqual(report["command_id"], command["command_id"])
            self.assertEqual(report["case_id"], command["case_id"])
            self.assertEqual(outcome["resource_cleanup"]["status"], "CLEANED")
            for area in command["resource_binding"]["areas"].values():
                self.assertFalse(Path(area).exists(), "successful writable scratch/report leaves are released")
            self.assertEqual(outcome["receiver"], "CODEX_SANDBOX_PERMISSION_PROFILE")
            if mode == "local-tcp":
                resource_support.BuildResourceIntegrationTests.check_tcp_observation(self, command, fixture.workspace)
        self.assertEqual(len([event for event in checks if event["payload"]["command_id"] == crashed[0]]), 1)
        self.assertEqual((fixture.workspace / "src/reader.py").read_text(), support.GOOD_READER)

    def test_native_local_http_temp_sqlite_reports_and_recovery(self):
        self.check_recovery("local-service")

    def test_native_local_tcp_http_temp_sqlite_reports_and_recovery(self):
        self.check_recovery("local-tcp")

    def test_native_local_tcp_start_failure_does_not_repair_product(self):
        holder = resource_support.BuildResourceIntegrationTests()
        self.addCleanup(holder.doCleanups)

        def factory(mode):
            fixture = self.fixture(mode)
            fixture.runner = NativeBuildRunner()
            return fixture

        holder.check_tcp_start_failure(fixture_factory=factory)

    @unittest.skipUnless(os.environ.get("HFFACTORY_TEST_RESOURCE_NETWORK"), "public read-only network opt-in required")
    def test_native_public_readonly_https_reports_and_recovery(self):
        self.check_recovery("remote-service")

    def check_native_dependency_binding(self, access):
        holder = resource_support.BuildResourceIntegrationTests()
        self.addCleanup(holder.doCleanups)

        def factory():
            fixture = self.fixture("pass")
            fixture.runner = NativeBuildRunner()
            return fixture

        holder.check_protected_dependency_resolution(access, fixture_factory=factory)

    def test_native_bound_context_keeps_oracle_separate_from_product_cwd(self):
        self.check_native_dependency_binding("context")

    def test_native_explicit_argument_keeps_oracle_separate_from_product_cwd(self):
        self.check_native_dependency_binding("argument")

    def product_copy_holder(self):
        holder = resource_support.BuildResourceIntegrationTests()
        self.addCleanup(holder.doCleanups)

        def factory():
            fixture = self.fixture("pass")
            fixture.runner = NativeBuildRunner()
            return fixture

        return holder, factory

    def test_native_product_copy_relative_build_permissions_and_capture_recovery(self):
        holder, factory = self.product_copy_holder()
        holder.check_product_copy_recovery(fixture_factory=factory, native_boundaries=True)

    def test_native_product_copy_cleaned_result_recovery_without_recopy_or_replay(self):
        holder, factory = self.product_copy_holder()
        holder.check_product_copy_recovery(after_cleanup=True, fixture_factory=factory, native_boundaries=True)

    def test_native_product_copy_source_edit_after_cleanup_holds_and_restores_without_replay(self):
        holder, factory = self.product_copy_holder()
        holder.check_product_copy_source_recovery(after_cleanup=True, final_check=True, fixture_factory=factory)

    def test_native_product_copy_keeps_wrong_product_rejected_and_failed_outputs(self):
        holder, factory = self.product_copy_holder()
        holder.check_product_copy_wrong_product(fixture_factory=factory)


if __name__ == "__main__":
    unittest.main()
