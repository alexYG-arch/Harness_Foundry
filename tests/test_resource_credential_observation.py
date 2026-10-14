"""Credential capture, original verdicts and recovery without secret replay."""

from copy import deepcopy
import errno
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from harness_foundry_factory.local_process import CodexSandboxRunner, LocalCommand, classify_local_capture
from harness_foundry_factory.build_types import RequestValidationError
from harness_foundry_factory.process_observation import CommandObservation
from harness_foundry_factory.resource_credentials import SecretRedactor
from harness_foundry_factory.resource_observation import CredentialObservation, finish_resource_observation
from harness_foundry_factory.verification_resources import cleanup_resources, validate_resources
import test_verification_resources as support


TOKEN = "synthetic-credential-838ac951"


class CredentialObservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.VerificationResourcesTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.config["profiles"]["sqlite"]["credentials"] = {
            "API_TOKEN": {"ref": "env:FOUNDRY_SYNTHETIC_TOKEN", "purpose": "Test API authentication"}}

    def completed(self, *, token=TOKEN, diagnostic=None, exit_code=0, timed_out=False, bad_route=False):
        binding = self.fixture.binding()
        verdict = self.fixture.verdict(binding)
        verdict["diagnostic"] = token if diagnostic is None else diagnostic
        if bad_route:
            verdict.update(status="CHECKS_FAILED", failure_kind="ASSERTION", repair_artifact_ids=[token])
            verdict["checks"][0]["status"] = "FAIL"
        staging = Path(binding["areas"]["report-staging"])
        (staging / "summary.json").write_text(json.dumps(verdict))
        (staging / "detail.txt").write_text(token)
        journal = CommandObservation(self.fixture.base / "observation", "CMD", "LOCAL")
        self.addCleanup(journal.close)
        capture = {"exit_code": exit_code, "timed_out": timed_out, "stdout": "", "stderr": "",
                   "output_truncated": False}
        CredentialObservation(journal, binding, SecretRedactor([token])).captured(capture)
        raw = CommandObservation.recover(journal.root, "CMD", "LOCAL")
        return binding, journal, raw

    def test_prepare_and_allocation_keep_only_references_without_resolving_environment(self):
        with patch("harness_foundry_factory.resource_credentials.os.environ.get", side_effect=AssertionError("no lookup")):
            binding = self.fixture.binding()
        self.assertEqual(binding["profile"]["credentials"], self.config["profiles"]["sqlite"]["credentials"])
        self.assertNotIn("FOUNDRY_CREDENTIAL_API_TOKEN", binding["env"])
        self.assertNotIn(TOKEN, json.dumps(binding))
        bad = deepcopy(self.config)
        bad["profiles"]["sqlite"]["credentials"]["API_TOKEN"]["value"] = TOKEN
        with self.assertRaises(RequestValidationError) as caught:
            validate_resources(bad, self.fixture.plan)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_original_status_is_judged_before_report_redaction(self):
        binding, journal, raw = self.completed(token="PASS")
        archived = json.loads((journal.root / "reports/summary.json").read_text())
        self.assertEqual(archived["checks"][0]["status"], "[REDACTED]")
        result = finish_resource_observation(raw, binding, journal.root)
        self.assertEqual(result["status"], "PASS")
        with patch("harness_foundry_factory.resource_credentials.resolve_credentials", side_effect=AssertionError("no lookup")):
            recovered = finish_resource_observation({}, binding, journal.root)
        self.assertEqual(recovered["status"], "PASS")

    def _assert_json_shaped_secret_is_safe_after_recovery(self, token, diagnostic):
        binding, journal, raw = self.completed(token=token, diagnostic=diagnostic)
        result = finish_resource_observation(raw, binding, journal.root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["resource_check_counts"]["PASS"], 2)
        self.assertEqual(result["resource_cleanup"]["status"], "CLEANED")
        self.assertFalse(Path(binding["areas"]["report-staging"]).exists())
        self.assertEqual(json.loads((journal.root / "reports/summary.json").read_text())["diagnostic"], "[REDACTED]")
        self.assertEqual(json.loads((journal.root / "reports/detail.txt").read_text()), "[REDACTED]")
        self.assertNotIn(token, json.dumps(result))
        for path in journal.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(token.encode(), path.read_bytes())
        with patch("harness_foundry_factory.resource_credentials.resolve_credentials", side_effect=AssertionError("no lookup")), \
             patch("harness_foundry_factory.resource_observation.collect_resource_reports", side_effect=AssertionError("no replay")):
            recovered = finish_resource_observation({}, binding, journal.root)
        self.assertEqual(recovered["status"], "PASS")
        self.assertEqual(recovered["resource_check_counts"], result["resource_check_counts"])
        self.assertEqual(recovered["resource_cleanup"], result["resource_cleanup"])

    def test_numeric_secret_in_json_scalar_and_plain_attachment_is_safe_after_recovery(self):
        token = "123456789987654321"
        self._assert_json_shaped_secret_is_safe_after_recovery(token, int(token))

    def test_json_array_shaped_secret_in_plain_attachment_is_safe_after_recovery(self):
        self._assert_json_shaped_secret_is_safe_after_recovery("[123]", "[123]")

    def test_json_object_shaped_secret_in_plain_attachment_is_safe_after_recovery(self):
        self._assert_json_shaped_secret_is_safe_after_recovery("{}", "{}")

    def test_secret_path_in_cleanup_error_is_safe_and_cached_without_repeating_cleanup(self):
        binding, journal, raw = self.completed()
        private_path = str(Path(binding["areas"]["scratch"]) / TOKEN)
        error = PermissionError(errno.EACCES, "permission denied", private_path)
        with patch("harness_foundry_factory.verification_resources.shutil.rmtree", side_effect=error) as remove:
            result = finish_resource_observation(raw, binding, journal.root)
        self.assertEqual(remove.call_count, 1)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertEqual(result["resource_cleanup"]["status"], "CLEANUP_WARNING")
        self.assertEqual(result["resource_cleanup"]["root"], binding["root"])
        self.assertTrue(Path(binding["areas"]["scratch"]).exists())
        # The controller persists this returned payload; it must already be safe.
        control_record = json.dumps({"command_id": "CMD", "observation": result})
        self.assertNotIn(TOKEN, control_record)
        persisted = json.loads((journal.root / "resource-cleanup.json").read_text())
        self.assertEqual(persisted, result["resource_cleanup"])
        for path in journal.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes())
        with patch("harness_foundry_factory.resource_credentials.resolve_credentials", side_effect=AssertionError("no lookup")), \
             patch("harness_foundry_factory.resource_observation.collect_resource_reports", side_effect=AssertionError("no replay")), \
             patch("harness_foundry_factory.resource_observation.cleanup_resources", side_effect=AssertionError("cached warning")):
            recovered = finish_resource_observation({}, binding, journal.root)
        self.assertEqual(recovered["status"], "PASS")
        self.assertEqual(recovered["resource_cleanup"], persisted)
        self.assertNotIn(TOKEN, json.dumps(recovered))

    def test_secret_path_in_cleanup_record_write_error_is_safe_without_changing_verdict(self):
        binding, journal, raw = self.completed()
        original_open = Path.open
        def fail_cleanup_record(path, *args, **kwargs):
            if path == journal.root / "resource-cleanup.pending":
                raise OSError(errno.EACCES, "permission denied", str(journal.root / TOKEN))
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", new=fail_cleanup_record):
            result = finish_resource_observation(raw, binding, journal.root)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertEqual(result["resource_cleanup"]["status"], "CLEANUP_WARNING")
        self.assertEqual(result["resource_cleanup"]["cleanup_result"]["status"], "CLEANED")
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertFalse((journal.root / "resource-cleanup.json").exists())
        self.assertTrue((journal.root / "resource-result.json").exists())

    def test_uncredentialed_cleanup_error_retains_existing_diagnostic(self):
        self.config["profiles"]["sqlite"].pop("credentials")
        binding = self.fixture.binding()
        error = PermissionError(errno.EACCES, "permission denied", str(Path(binding["areas"]["scratch"]) / "old-diagnostic"))
        with patch("harness_foundry_factory.verification_resources.shutil.rmtree", side_effect=error):
            result = cleanup_resources(binding, True)
        self.assertEqual(result["status"], "CLEANUP_WARNING")
        self.assertEqual(result["reason"], str(error))

    def test_uncredentialed_cleanup_record_write_error_retains_existing_diagnostic(self):
        self.config["profiles"]["sqlite"].pop("credentials")
        binding = self.fixture.binding()
        self.fixture.write_reports(binding)
        root = self.fixture.base / "plain-observation"
        original_open = Path.open
        error = OSError(errno.EACCES, "permission denied", str(root / "old-diagnostic"))
        def fail_cleanup_record(path, *args, **kwargs):
            if path == root / "resource-cleanup.pending":
                raise error
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", new=fail_cleanup_record):
            result = finish_resource_observation({"status": "PASS", "exit_code": 0}, binding, root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["resource_cleanup"]["status"], "CLEANUP_WARNING")
        self.assertEqual(result["resource_cleanup"]["reason"], str(error))

    def test_secret_in_repair_identifier_cannot_leak_or_route_a_masked_target(self):
        binding, journal, raw = self.completed(exit_code=1, bad_route=True)
        result = finish_resource_observation(raw, binding, journal.root)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertFalse(result["automatic_retry_allowed"])
        self.assertNotIn("repair_artifact_ids", result)
        for path in journal.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes())

    def test_saved_unknown_capture_is_not_upgraded_by_complete_reports(self):
        binding, journal, raw = self.completed(exit_code=-9, timed_out=True)
        for result in (finish_resource_observation(raw, binding, journal.root),
                       finish_resource_observation({}, binding, journal.root)):
            self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
            self.assertFalse(result["automatic_retry_allowed"])

    def test_missing_completion_never_recollects_raw_staging_or_resolves_new_secret(self):
        binding, journal, raw = self.completed()
        raw.pop("credential_reports")
        with patch("harness_foundry_factory.resource_observation.collect_resource_reports", side_effect=AssertionError("no recollection")):
            result = finish_resource_observation(raw, binding, journal.root)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertFalse(result["automatic_retry_allowed"])

    def test_missing_attachment_metadata_cannot_turn_partial_archive_into_pass(self):
        binding, journal, raw = self.completed()
        raw["credential_reports"]["reports"].pop()
        result = finish_resource_observation(raw, binding, journal.root)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")

    def test_saved_result_recovery_checks_archived_bytes_after_cleanup(self):
        binding, journal, raw = self.completed()
        self.assertEqual(finish_resource_observation(raw, binding, journal.root)["status"], "PASS")
        report = journal.root / "reports/detail.txt"
        report.write_text("changed archive")
        self.assertEqual(finish_resource_observation({}, binding, journal.root)["status"], "UNKNOWN_SIDE_EFFECT")
        report.unlink()
        self.assertEqual(finish_resource_observation({}, binding, journal.root)["status"], "UNKNOWN_SIDE_EFFECT")

    def test_capture_filters_streams_preview_and_callback_exceptions_before_persistence(self):
        runner = CodexSandboxRunner("/usr/bin/true", output_limit_bytes=18)
        journal = CommandObservation(self.fixture.base / "stream", "CMD", "LOCAL")
        self.addCleanup(journal.close)
        code = "import os;v=os.environ['FOUNDRY_CREDENTIAL_API_TOKEN'].encode();os.write(1,b'hello '+v);os.write(2,v)"
        def fail_after_safe_capture(capture):
            journal.captured(capture)
            raise RuntimeError(TOKEN)
        result = runner._capture([sys.executable, "-B", "-c", code], self.fixture.base, 5,
            environment={"FOUNDRY_CREDENTIAL_API_TOKEN": TOKEN}, redactor=SecretRedactor([TOKEN]),
            stream_sink=journal.write, on_capture=fail_after_safe_capture)
        self.assertTrue(result["output_truncated"])
        self.assertEqual(classify_local_capture(result)["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertNotIn(TOKEN, json.dumps(result))
        for path in journal.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes())

    def test_raw_byte_budget_still_applies_when_output_is_shortened(self):
        runner = CodexSandboxRunner("/usr/bin/true", stream_limit_bytes=32)
        code = "import os;os.write(1,os.environ['FOUNDRY_CREDENTIAL_API_TOKEN'].encode()*8)"
        result = runner._capture([sys.executable, "-B", "-c", code], self.fixture.base, 5,
            environment={"FOUNDRY_CREDENTIAL_API_TOKEN": TOKEN}, redactor=SecretRedactor([TOKEN]))
        self.assertEqual(result["capture_error"], "PROCESS_STREAM_LIMIT_EXCEEDED")
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_failure_before_report_completion_has_no_recoverable_success(self):
        binding = self.fixture.binding()
        journal = CommandObservation(self.fixture.base / "failed-collection", "CMD", "LOCAL")
        self.addCleanup(journal.close)
        observer = CredentialObservation(journal, binding, SecretRedactor([TOKEN]))
        with patch("harness_foundry_factory.resource_observation.collect_resource_reports", side_effect=OSError(TOKEN)):
            captured = CodexSandboxRunner("/usr/bin/true")._capture(
                [sys.executable, "-B", "-c", "print('completed')"], self.fixture.base, 5,
                redactor=SecretRedactor([TOKEN]), on_capture=observer.captured)
        self.assertNotIn(TOKEN, json.dumps(captured))
        self.assertIsNone(CommandObservation.recover(journal.root, "CMD", "LOCAL"))
        result = finish_resource_observation(classify_local_capture(captured), binding, journal.root)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertFalse(result["automatic_retry_allowed"])

    def test_provider_runs_only_for_workload_and_never_mutates_plain_command(self):
        scratch = self.fixture.base / "scratch"; scratch.mkdir()
        command = LocalCommand.prepare(argv=["/usr/bin/true"], cwd=self.fixture.base,
            read_roots=[self.fixture.base, "/usr/bin/true"], write_roots=[scratch], network={"mode": "NONE"})
        runner = CodexSandboxRunner("/usr/bin/true")
        help_result = {"exit_code": 0, "timed_out": False, "stdout":
            "[COMMAND] --permission-profile --include-managed-config --cd", "stderr": ""}
        completed = help_result | {"stdout": ""}
        seen = []
        def provider(observation):
            seen.append(True)
            return {"FOUNDRY_CREDENTIAL_API_TOKEN": TOKEN}, SecretRedactor([TOKEN]), observation
        with patch.object(runner, "_capture", side_effect=[help_result, completed, completed]) as capture:
            self.assertEqual(runner.run(command, credential_provider=provider)["status"], "PASS")
        self.assertEqual(seen, [True])
        for call in capture.call_args_list[:2]:
            self.assertNotIn("environment", call.kwargs)
            self.assertNotIn("redactor", call.kwargs)
        self.assertEqual(capture.call_args_list[-1].kwargs["environment"], {"FOUNDRY_CREDENTIAL_API_TOKEN": TOKEN})
        self.assertEqual(command.environment, ())
