"""A2 handoff preserves existing resource outcomes and durable recovery."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_resource_lifecycle import (
    finish_command_observation, prepare_resource_invocation,
    recover_command_observation, resource_dispatch_hooks,
)
from harness_foundry_factory.build_types import RequestValidationError
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.verification_resources import validate_product_copy_sources
import test_verification_resources as support


class ResourceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.VerificationResourcesTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.workspace = self.fixture.base / "product"
        self.workspace.mkdir()
        (self.workspace / "input.txt").write_text("declared input\n")
        self.invocation = {
            "phase": "VERIFICATION", "executor": "LOCAL", "resource_profile_ref": "sqlite",
            "cwd": str(self.workspace), "read_roots": [str(self.workspace)],
            "write_roots": [], "argv": ["python", "checker.py", "resource://scratch/data.sqlite3"],
            "timeout_seconds": 900,
        }

    def prepare(self):
        return prepare_resource_invocation(
            self.invocation, config=self.fixture.config, identity=self.fixture.identity,
            workspace_root=self.workspace, checked_artifacts={"INPUT": {"path": "input.txt"}},
            verifier_files={"checker.py": {"sha256": "protected-checker"}},
            verifier_root=str(self.fixture.base / "protected-checker"))

    def command(self, prepared):
        return {"command_id": "CMD", "executor": "LOCAL", "phase": "VERIFICATION",
                "observation_root": str(self.fixture.base / "observation"),
                "resource_binding": prepared["resource_binding"]}

    def test_prepare_keeps_permissions_binding_and_timeout_without_secret_lookup(self):
        profile = self.fixture.config["profiles"]["sqlite"]
        profile["credentials"] = {"API": {"ref": "env:SYNTHETIC", "purpose": "Fixture authentication"}}
        for network in ({"mode": "NONE"}, {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"},
                        {"mode": "REMOTE_SERVICE", "allowed_hosts": ["example.com"]}):
            with self.subTest(network=network):
                profile["network"] = network
                original = deepcopy(self.invocation)
                with patch("harness_foundry_factory.build_resource_lifecycle.resolve_credentials",
                           side_effect=AssertionError("preparation must not resolve credentials")):
                    prepared, failure = self.prepare()
                self.assertIsNone(failure)
                self.assertEqual(self.invocation, original)
                self.assertEqual(prepared["network"], network)
                self.assertEqual(prepared["timeout_seconds"], 900)
                binding = prepared["resource_binding"]
                self.assertEqual(prepared["write_roots"], list(binding["areas"].values()))
                self.assertEqual(prepared["argv"][-1], str(Path(binding["areas"]["scratch"]) / "data.sqlite3"))
                self.assertEqual(binding["env"]["FOUNDRY_VERIFIER_ROOT"], binding["verifier_root"])
                self.assertEqual(binding["checked_artifacts"], {"INPUT": {"path": "input.txt"}})
                self.assertNotIn("FOUNDRY_CREDENTIAL_API", binding["env"])

    def test_copy_keeps_original_sources_and_limits_generated_paths(self):
        self.fixture.config["profiles"]["sqlite"]["product_copy"] = {
            "files": ["input.txt"], "writable_paths": ["build"]}
        prepared, failure = self.prepare()
        self.assertIsNone(failure)
        binding = prepared["resource_binding"]
        copied = Path(prepared["cwd"])
        self.assertEqual((copied / "input.txt").read_bytes(), (self.workspace / "input.txt").read_bytes())
        self.assertIn(str(copied), prepared["read_roots"])
        self.assertNotIn(str(copied), prepared["write_roots"])
        self.assertIn(str(copied / "build"), prepared["write_roots"])
        self.assertEqual(validate_product_copy_sources(binding, self.workspace)["status"], "UNCHANGED")
        (self.workspace / "unrelated.txt").write_text("unlisted edit")
        self.assertEqual(validate_product_copy_sources(binding, self.workspace)["status"], "UNCHANGED")
        (self.workspace / "input.txt").write_text("changed source")
        self.assertEqual(validate_product_copy_sources(binding, self.workspace)["status"], "CHANGED")

    def test_known_preparation_failure_retains_binding_and_recovers_without_copy(self):
        self.fixture.config["profiles"]["sqlite"]["product_copy"] = {
            "files": ["missing.txt"], "writable_paths": ["build"]}
        prepared, failure = self.prepare()
        self.assertEqual(failure["status"], "VALIDATION_FAILED")
        self.assertFalse(failure["workload_started"])
        self.assertFalse(failure["automatic_retry_allowed"])
        self.assertEqual(failure["reason_code"], "PRODUCT_COPY_PREPARATION_FAILED")
        command = self.command(prepared)
        binding = command["resource_binding"]
        self.assertTrue((Path(binding["root"]) / "product").exists())
        observation = CommandObservation(command["observation_root"], "CMD", "LOCAL")
        observation.finished(failure)
        observation.close()
        with patch("harness_foundry_factory.build_resource_lifecycle.allocate_resources",
                   side_effect=AssertionError("no reallocation")), \
             patch("harness_foundry_factory.build_resource_lifecycle.materialize_product_copy",
                   side_effect=AssertionError("no recopy")):
            recovered = recover_command_observation(command)
        self.assertFalse(recovered["workload_started"])
        self.assertEqual(recovered["resource_cleanup"]["status"], "RETAINED")
        self.assertEqual(recovered["resource_binding"], binding)

    def test_successful_collection_and_cleanup_recover_without_staging_or_new_resources(self):
        prepared, _ = self.prepare()
        command = self.command(prepared)
        binding = command["resource_binding"]
        self.fixture.write_reports(binding)
        raw = {"status": "PASS", "exit_code": 0}
        observation = CommandObservation(command["observation_root"], "CMD", "LOCAL")
        observation.finished(raw)
        observation.close()
        result = finish_command_observation(raw, command)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["resource_cleanup"]["status"], "CLEANED")
        self.assertFalse(Path(binding["areas"]["report-staging"]).exists())
        with patch("harness_foundry_factory.build_resource_lifecycle.allocate_resources",
                   side_effect=AssertionError("no reallocation")), \
             patch("harness_foundry_factory.resource_observation.collect_resource_reports",
                   side_effect=AssertionError("no report recollection")), \
             patch("harness_foundry_factory.resource_observation.cleanup_resources",
                   side_effect=AssertionError("no repeated cleanup")):
            recovered = recover_command_observation(command)
        self.assertEqual(recovered, result)

    def test_incomplete_observation_remains_unknown_without_resource_settlement(self):
        prepared, _ = self.prepare()
        command = self.command(prepared)
        observation = CommandObservation(command["observation_root"], "CMD", "LOCAL")
        observation.write("stdout", b"partial response")
        observation.close()
        with patch("harness_foundry_factory.build_resource_lifecycle.finish_resource_observation",
                   side_effect=AssertionError("partial capture is not a completed result")):
            self.assertIsNone(recover_command_observation(command))
        self.assertTrue(Path(prepared["resource_binding"]["areas"]["scratch"]).is_dir())

    def test_credentials_are_lazy_raw_judgment_precedes_redaction_and_recovery_never_resolves(self):
        self.fixture.config["profiles"]["sqlite"]["credentials"] = {
            "API": {"ref": "env:FOUNDRY_A2_SYNTHETIC", "purpose": "Fixture authentication"}}
        prepared, _ = self.prepare()
        command = self.command(prepared)
        binding = command["resource_binding"]
        observation = CommandObservation(command["observation_root"], "CMD", "LOCAL")
        self.addCleanup(observation.close)
        with patch("harness_foundry_factory.build_resource_lifecycle.resolve_credentials",
                   side_effect=AssertionError("hook creation must remain lazy")):
            hooks = resource_dispatch_hooks(prepared, observation)
        with patch.dict("os.environ", {"FOUNDRY_A2_SYNTHETIC": "PASS"}):
            environment, _, observer = hooks["credential_provider"](observation)
        self.assertEqual(environment, {"FOUNDRY_CREDENTIAL_API": "PASS"})
        self.fixture.write_reports(binding)
        observer.captured({"exit_code": 0, "timed_out": False, "stdout": "", "stderr": "",
                           "output_truncated": False})
        with patch("harness_foundry_factory.build_resource_lifecycle.resolve_credentials",
                   side_effect=AssertionError("recovery must never resolve credentials")):
            result = recover_command_observation(command)
            again = recover_command_observation(command)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(again, result)
        report = json.loads((Path(command["observation_root"]) / "reports/summary.json").read_text())
        self.assertEqual(report["checks"][0]["status"], "[REDACTED]")
        self.assertEqual(result["resource_check_counts"]["PASS"], 2)

    def test_credential_provider_keeps_original_error_and_bound_local_requirement(self):
        self.fixture.config["profiles"]["sqlite"]["credentials"] = {
            "API": {"ref": "env:FOUNDRY_A2_MISSING", "purpose": "Fixture authentication"}}
        prepared, _ = self.prepare()
        observer = object()
        hooks = resource_dispatch_hooks(prepared, observer)
        with patch.dict("os.environ", {}, clear=True), self.assertRaisesRegex(ValueError, "test credential unavailable"):
            hooks["credential_provider"](observer)
        for changes, observation in (({"phase": "IMPLEMENTATION"}, observer),
                                     ({"executor": "CODEX"}, observer), ({}, None)):
            with self.subTest(changes=changes), self.assertRaisesRegex(RequestValidationError, "bound local verification"):
                resource_dispatch_hooks({**prepared, **changes}, observation)

    def test_unresourced_results_and_unknown_effects_do_not_gain_success(self):
        raw = {"status": "UNKNOWN_SIDE_EFFECT", "reason_code": "EXISTING_UNKNOWN_WINDOW"}
        self.assertIs(finish_command_observation(raw, {}), raw)
        self.assertEqual(resource_dispatch_hooks(self.invocation, None), {})
        prepared, _ = self.prepare()
        self.fixture.write_reports(prepared["resource_binding"])
        result = finish_command_observation(raw, self.command(prepared))
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(result["resource_cleanup"]["status"], "RETAINED")
        self.assertFalse(result["automatic_retry_allowed"])


if __name__ == "__main__":
    unittest.main()
