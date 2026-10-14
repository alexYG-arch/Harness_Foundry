"""Resource scopes, real disposable SQLite, and host-owned report provenance."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_replan import adapt_build_plan
from harness_foundry_factory.build_types import RequestValidationError
from harness_foundry_factory.verification_resources import (
    allocate_resources, cleanup_resources, collect_resource_reports,
    resolve_resource_argv, validate_resources, validate_structured_result,
    materialize_product_copy, validate_product_copy, validate_product_copy_sources,
)
from test_build_plan import request_fixture


class VerificationResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.request = request_fixture()
        self.plan = self.request["plan"]
        self.plan["schema_version"] = "1.2"
        self.plan["workpacks"][0]["verification"][0]["resource_profile_ref"] = "sqlite"
        self.config = {"schema_version": "1.0", "root": str(self.base / "runs"), "profiles": {
            "sqlite": {"writable_areas": ["scratch", "report-staging"], "network": {"mode": "NONE"},
                       "services": [], "result_protocol": "STRUCTURED_V1", "required_checks": ["transaction", "migration"],
                       "report_files": ["summary.json", "detail.txt"],
                       "retention": {"success": "REPORTS_ONLY", "failure_days": 7}}}}
        self.identity = {"program_id": "P", "prepared_event_id": "PREP", "attempt_id": "ATTEMPT",
                         "case_id": "READ-ROWS", "command_id": "CMD"}

    def binding(self, **identity):
        config = validate_resources(self.config, self.plan, [self.base / "product", self.base / "checker"])
        return allocate_resources(config, "sqlite", {**self.identity, **identity})

    def verdict(self, binding):
        return {"schema_version": "1.0", "case_id": binding["case_id"], "command_id": binding["command_id"],
                "status": "CHECKS_PASS", "checks": [{"id": item, "status": "PASS"} for item in binding["required_checks"]],
                "errors": []}

    def write_reports(self, binding):
        root = Path(binding["areas"]["report-staging"])
        (root / "summary.json").write_text(json.dumps(self.verdict(binding)))
        (root / "detail.txt").write_text("Both disposable SQLite obligations checked.\n")

    def test_plan12_preserves_11_contracts_and_replan_resource_reference(self):
        self.plan["workpacks"][0]["effects"] = {
            "required": ["src/reader.py"], "allowed": ["src/reader.py"], "must_preserve": []}
        self.request["requirement_ir"]["acceptance_cases"][0]["required_artifact_ids"] = ["READER-SOURCE"]
        compile_build_plan(self.request["requirement_ir"], self.plan)
        changed = deepcopy(self.plan)
        changed["workpacks"][0]["verification"][0]["resource_profile_ref"] = "networked"
        scope = {"task_write_roots": {task["workpack_id"]: ["/fixture/product"] for task in self.plan["workpacks"]}}
        with self.assertRaises(RequestValidationError):
            adapt_build_plan(self.plan, changed, scope)
        self.plan["schema_version"] = "1.1"
        with self.assertRaises(RequestValidationError):
            compile_build_plan(self.request["requirement_ir"], self.plan)

    def test_scope_is_optional_for_legacy_and_required_for_references(self):
        with self.assertRaises(RequestValidationError):
            validate_resources(None, self.plan)
        self.plan["workpacks"][0]["verification"][0].pop("resource_profile_ref")
        self.plan["schema_version"] = "1.0"
        self.assertIsNone(validate_resources(None, self.plan))
        with self.assertRaises(RequestValidationError):
            validate_resources(self.config, self.plan)

    def test_old_plan_resource_like_literals_keep_original_argv_semantics(self):
        self.plan["workpacks"][0]["verification"][0].pop("resource_profile_ref")
        for version in ("1.0", "1.1"):
            for location in ("local_argv", "verification"):
                with self.subTest(version=version, location=location):
                    plan = deepcopy(self.plan)
                    plan["schema_version"] = version
                    if location == "local_argv":
                        plan["workpacks"][0]["local_argv"] = ["python", "resource://old-input"]
                    else:
                        plan["workpacks"][0]["verification"][0]["argv"].append("resource://old-input")
                    original = deepcopy(plan)
                    self.assertIsNone(validate_resources(None, plan))
                    self.assertEqual(plan, original)
                    plan["schema_version"] = "1.2"
                    with self.assertRaises(RequestValidationError):
                        validate_resources(None, plan)

    def test_invalid_resource_roots_and_unknown_profile_rejected_before_allocation(self):
        for root in (str(self.base / "product"), str(self.base / "product" / "scratch"), str(self.base), "/"):
            with self.subTest(root=root), self.assertRaises(RequestValidationError):
                validate_resources({**self.config, "root": root}, self.plan, [self.base / "product"])
        self.assertFalse((self.base / "runs").exists())
        self.plan["workpacks"][0]["verification"][0]["resource_profile_ref"] = "missing"
        with self.assertRaises(RequestValidationError):
            validate_resources(self.config, self.plan)

    def test_fresh_leaves_support_sqlite_wal_rollback_and_migration(self):
        binding = self.binding()
        scratch = Path(binding["areas"]["scratch"])
        database = sqlite3.connect(scratch / "test.sqlite3")
        try:
            self.assertEqual(database.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
            database.execute("CREATE TABLE items (name TEXT)")
            database.execute("INSERT INTO items VALUES ('retained')")
            database.commit()
            database.execute("INSERT INTO items VALUES ('rolled-back')")
            database.rollback()
            database.execute("ALTER TABLE items ADD COLUMN migration INTEGER DEFAULT 2")
            self.assertEqual(database.execute("SELECT * FROM items").fetchall(), [("retained", 2)])
            self.assertTrue((scratch / "test.sqlite3-wal").exists())
            self.assertTrue((scratch / "test.sqlite3-shm").exists())
        finally:
            database.close()
        next_binding = self.binding(command_id="CMD2")
        self.assertNotEqual(next_binding["areas"], binding["areas"])
        self.assertFalse((Path(next_binding["areas"]["scratch"]) / "test.sqlite3").exists())
        self.assertEqual(binding["env"]["TMPDIR"], str(scratch))
        self.assertEqual(binding["env"]["FOUNDRY_COMMAND_ID"], "CMD")
        self.assertNotIn(str(Path(binding["root"]).parent), binding["write_roots"])
        self.assertEqual(len(Path(binding["root"]).name), 12)

    def test_argv_hydration_rejects_escape_and_preserves_plain_arguments(self):
        binding = self.binding()
        argv = resolve_resource_argv(["--output", "resource://scratch/data.sqlite3", "literal-$HOME"], binding)
        self.assertEqual(argv, ["--output", str(Path(binding["areas"]["scratch"]) / "data.sqlite3"), "literal-$HOME"])
        for value in ("resource://scratch/../other", "resource://work/output", "resource://scratch/a//b"):
            with self.subTest(value=value), self.assertRaises(RequestValidationError):
                resolve_resource_argv([value], binding)
        (Path(binding["areas"]["scratch"]) / "outside").symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(RequestValidationError):
            resolve_resource_argv(["resource://scratch/outside/file"], binding)

    def test_reserved_argv_errors_are_rejected_in_prepare_without_allocating_resources(self):
        check = self.plan["workpacks"][0]["verification"][0]
        for argument in ("resource://scratch/../escape", "resource://work/file", "resource://scratch/"):
            with self.subTest(argument=argument), self.assertRaises(RequestValidationError):
                check["argv"] = ["executable://python", argument]
                validate_resources(self.config, self.plan)
        check["argv"] = ["executable://python", "resource://scratch/data.db"]
        validate_resources(self.config, self.plan)
        check.pop("resource_profile_ref")
        with self.assertRaises(RequestValidationError):
            validate_resources(self.config, self.plan)
        with self.assertRaises(RequestValidationError):
            validate_resources(None, self.plan)
        check["argv"] = ["plain-cli", "unchanged-value"]
        self.plan["workpacks"][1]["local_argv"] = ["plain-cli", "resource://scratch/data.db"]
        with self.assertRaises(RequestValidationError):
            validate_resources(self.config, self.plan)
        self.assertFalse((self.base / "runs").exists())

    def test_collection_is_durable_and_recovery_does_not_read_new_staging(self):
        binding = self.binding()
        self.write_reports(binding)
        observation = self.base / "observation"
        observation.mkdir()
        collected = collect_resource_reports(binding, observation)
        self.assertEqual(collected["report_errors"], [])
        self.assertEqual(validate_structured_result(collected["verdict"], binding, 0)["status"], "PASS")
        self.assertTrue(all(row["sha256"] for row in collected["reports"]))
        self.assertEqual(cleanup_resources(binding, True)["status"], "CLEANED")
        self.assertFalse(Path(binding["areas"]["scratch"]).exists())
        self.assertEqual(collect_resource_reports(binding, observation), collected)

    def test_partial_collection_recovers_existing_host_report_and_rejects_corrupt_summary(self):
        binding = self.binding()
        self.write_reports(binding)
        observation = self.base / "partial-observation"
        (observation / "reports").mkdir(parents=True)
        # A crash after copying summary but before detail leaves a valid host
        # attachment, never permission to redispatch the checker.
        summary = observation / "reports" / "summary.json"
        summary.write_text(json.dumps(self.verdict(binding)))
        (Path(binding["areas"]["report-staging"]) / "summary.json").write_text("truncated")
        recovered = collect_resource_reports(binding, observation)
        self.assertEqual(recovered["report_errors"], [])
        self.assertEqual(validate_structured_result(recovered["verdict"], binding, 0)["status"], "PASS")
        summary.write_text("{\"schema_version\":")
        corrupted = collect_resource_reports(binding, observation)
        self.assertTrue(corrupted["report_errors"])
        self.assertIsNone(corrupted["verdict"])

    def test_report_pending_names_remain_distinct_after_cleanup_and_recovery(self):
        variants = [
            ["summary.json.pending", "summary.json"],
            ["summary.json", "summary.json.pending"],
            ["summary.json", "nested/detail.pending", "nested/detail"],
            ["summary.json", "nested/detail", "nested/detail.pending"],
        ]
        for index, files in enumerate(variants):
            with self.subTest(files=files):
                self.config["profiles"]["sqlite"]["report_files"] = files
                binding = self.binding(command_id=f"FILES-{index}")
                staging = Path(binding["areas"]["report-staging"])
                expected = {}
                for relative in files:
                    payload = (json.dumps(self.verdict(binding)).encode() if relative == "summary.json"
                               else f"Evidence for {relative}\n".encode())
                    path = staging / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
                    expected[relative] = payload
                observation = self.base / f"files-{index}"
                observation.mkdir()
                collected = collect_resource_reports(binding, observation)
                self.assertEqual(collected["report_errors"], [])
                self.assertEqual(validate_structured_result(collected["verdict"], binding, 0)["status"], "PASS")
                self.assertEqual(cleanup_resources(binding, True)["status"], "CLEANED")
                self.assertEqual(collect_resource_reports(binding, observation), collected)
                for relative, payload in expected.items():
                    self.assertEqual((observation / "reports" / relative).read_bytes(), payload)
                self.assertEqual(list(observation.iterdir()), [observation / "reports"])

    def test_interrupted_report_promotion_preserves_prior_attachment_and_recovers(self):
        self.config["profiles"]["sqlite"]["report_files"] = ["summary.json.pending", "summary.json"]
        binding = self.binding()
        self.write_reports(binding)
        staging = Path(binding["areas"]["report-staging"])
        attachment = staging / "summary.json.pending"
        attachment.write_bytes(b"original attachment")
        observation = self.base / "interrupted-observation"
        observation.mkdir()
        replace = os.replace

        def interrupt_summary(source, target):
            self.assertFalse(Path(source).is_relative_to(observation / "reports"))
            if Path(target).name == "summary.json":
                raise OSError("interrupted before atomic promotion")
            return replace(source, target)

        with patch("harness_foundry_factory.verification_resources.os.replace", side_effect=interrupt_summary):
            interrupted = collect_resource_reports(binding, observation)
        self.assertEqual([row["name"] for row in interrupted["report_errors"]], ["summary.json"])
        self.assertIsNone(interrupted["verdict"])
        self.assertFalse((observation / "reports" / "summary.json").exists())
        self.assertEqual(cleanup_resources(binding, False)["status"], "RETAINED")
        attachment.write_bytes(b"later staging content is not authority")
        recovered = collect_resource_reports(binding, observation)
        self.assertEqual(recovered["report_errors"], [])
        self.assertEqual(validate_structured_result(recovered["verdict"], binding, 0)["status"], "PASS")
        self.assertEqual((observation / "reports" / "summary.json.pending").read_bytes(), b"original attachment")
        self.assertEqual(cleanup_resources(binding, True)["status"], "CLEANED")
        self.assertEqual(collect_resource_reports(binding, observation), recovered)
        self.assertEqual(list(observation.iterdir()), [observation / "reports"])

    def test_report_symlink_hardlink_directory_and_fifo_are_not_archived(self):
        for kind in ("symlink", "hardlink", "directory", "fifo"):
            with self.subTest(kind=kind):
                binding = self.binding(command_id=kind)
                self.write_reports(binding)
                report = Path(binding["areas"]["report-staging"]) / "detail.txt"
                report.unlink()
                outside = self.base / (kind + ".txt")
                outside.write_text("private unrelated data")
                if kind == "symlink":
                    report.symlink_to(outside)
                elif kind == "hardlink":
                    os.link(outside, report)
                elif kind == "directory":
                    report.mkdir()
                else:
                    os.mkfifo(report)
                observation = self.base / (kind + "-observed")
                observation.mkdir()
                collected = collect_resource_reports(binding, observation)
                self.assertEqual(len(collected["report_errors"]), 1)
                self.assertIsNone(collected["verdict"])
                self.assertFalse((observation / "reports" / "detail.txt").exists())

    def test_incomplete_or_unbound_results_do_not_repair_product(self):
        binding = self.binding()
        mutations = [lambda value: value.update(command_id="OLD"), lambda value: value.update(checks=[]),
                     lambda value: value["checks"].pop(), lambda value: value["checks"].append(value["checks"][0]),
                     lambda value: value["checks"][0].update(status="SKIP"),
                     lambda value: value["checks"][0].update(status="ERROR"),
                     lambda value: value.update(errors=["discovery failed"]),
                     lambda value: value.update(status="CHECKS_FAILED", failure_kind="ASSERTION")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = self.verdict(binding)
                mutate(value)
                result = validate_structured_result(value, binding, 0)
                self.assertEqual(result["status"], "VALIDATION_FAILED")
                self.assertFalse(result["automatic_retry_allowed"])
        self.assertEqual(validate_structured_result(self.verdict(binding), binding, 1)["status"], "VALIDATION_FAILED")

    def test_actual_assertion_routes_native_repair_and_failure_evidence_is_retained(self):
        binding = self.binding()
        value = self.verdict(binding)
        value.update(status="CHECKS_FAILED", failure_kind="ASSERTION")
        value["checks"][0]["status"] = "FAIL"
        result = validate_structured_result(value, binding, 1)
        self.assertTrue(result["automatic_retry_allowed"])
        self.assertEqual(result["failure_domain"], "BUSINESS_ASSERTION")
        self.assertEqual(cleanup_resources(binding, False)["status"], "RETAINED")
        self.assertTrue(Path(binding["areas"]["scratch"]).exists())

    def test_local_socket_is_owned_and_remote_effects_must_be_resolved(self):
        profile = self.config["profiles"]["sqlite"]
        profile["network"] = {"mode": "LOCAL_SERVICE", "unix_sockets": ["resource://scratch/owned/service.sock"]}
        binding = self.binding()
        self.assertEqual(binding["network"]["unix_sockets"], [str(Path(binding["areas"]["scratch"]) / "owned/service.sock")])
        self.assertTrue(Path(binding["network"]["unix_sockets"][0]).parent.is_dir())
        verdict = self.verdict(binding)
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "VALIDATION_FAILED")
        verdict["services_stopped"] = True
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "PASS")
        profile["network"] = {"mode": "REMOTE_SERVICE", "allowed_hosts": ["example.com"]}
        binding = self.binding(command_id="REMOTE")
        verdict = self.verdict(binding)
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "UNKNOWN_SIDE_EFFECT")
        verdict["external_effects"] = "UNKNOWN"
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "UNKNOWN_SIDE_EFFECT")
        verdict["external_effects"] = "NONE"
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "PASS")
        verdict["command_id"] = "UNBOUND"
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "UNKNOWN_SIDE_EFFECT")

    def test_local_tcp_allocation_keeps_existing_identity_and_service_closure(self):
        profile = self.config["profiles"]["sqlite"]
        profile["network"] = {"mode": "LOCAL_SERVICE", "tcp": "LOOPBACK"}
        binding = self.binding()
        self.assertEqual(binding["network"], profile["network"])
        self.assertEqual(binding["command_id"], self.identity["command_id"])
        verdict = self.verdict(binding)
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "VALIDATION_FAILED")
        verdict["services_stopped"] = True
        self.assertEqual(validate_structured_result(verdict, binding, 0)["status"], "PASS")
        for invalid in ("ANY", True, ["LOOPBACK"]):
            profile["network"]["tcp"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(RequestValidationError):
                validate_resources(self.config, self.plan)

    def test_checker_auxiliary_file_list_is_explicit_and_relative(self):
        self.config["checker_files"] = ["helpers/assertions.py", "fixtures/case.json"]
        normalized = validate_resources(self.config, self.plan)
        self.assertEqual(normalized["checker_files"], self.config["checker_files"])
        self.config["checker_files"].append("../product.py")
        with self.assertRaises(RequestValidationError):
            validate_resources(self.config, self.plan)

    def product_binding(self):
        self.config["profiles"]["sqlite"]["product_copy"] = {
            "files": ["src/reader.py", "run-check"], "writable_paths": [".cache", "build/output"]}
        product = self.base / "product"
        (product / "src").mkdir(parents=True)
        (product / "src/reader.py").write_text("VALUE = 'working tree content'\n")
        (product / "run-check").write_text("#!/bin/sh\nexit 0\n")
        (product / "run-check").chmod(0o755)
        (product / "unlisted.txt").write_text("not copied")
        binding = self.binding()
        materialize_product_copy(binding, product)
        return binding, product

    def test_product_copy_is_opt_in_and_compatible_with_credentials(self):
        binding = self.binding()
        original = deepcopy(binding)
        self.assertIs(materialize_product_copy(binding, self.base / "unused"), binding)
        self.assertEqual(binding, original)
        self.assertEqual(validate_product_copy(binding)["status"], "NOT_REQUESTED")
        profile = self.config["profiles"]["sqlite"]
        profile["product_copy"] = {"files": ["source.py"], "writable_paths": [".cache"]}
        profile["credentials"] = {"TEST_TOKEN": {"ref": "env:FOUNDRY_TEST_TOKEN", "purpose": "test API"}}
        validate_resources(self.config, self.plan)
        self.assertFalse((self.base / "runs/unused").exists())

    def test_product_copy_contract_rejects_ambiguous_inputs_without_allocating(self):
        invalid = [
            {"files": [], "writable_paths": ["out"]},
            {"files": ["source.py"], "writable_paths": []},
            {"files": ["source.py", "source.py"], "writable_paths": ["out"]},
            {"files": ["source.py"], "writable_paths": ["out", "out"]},
            {"files": ["source.py"], "writable_paths": ["."]},
            {"files": ["../source.py"], "writable_paths": ["out"]},
            {"files": ["src/main.py"], "writable_paths": ["src"]},
            {"files": ["source.py"], "writable_paths": ["source.py/cache"]},
            {"files": ["source.py"], "writable_paths": ["source.py"]},
            {"files": ["src", "src/main.py"], "writable_paths": ["out"]},
            {"files": ["source.py"], "writable_paths": ["out"], "other": True},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(RequestValidationError):
                self.config["profiles"]["sqlite"]["product_copy"] = value
                validate_resources(self.config, self.plan)
        self.assertFalse((self.base / "runs").exists())

    def test_product_copy_copies_declared_current_bytes_with_independent_inputs(self):
        binding, product = self.product_binding()
        copied = binding["product_copy"]
        root = Path(copied["root"])
        self.assertEqual(root, Path(binding["root"]) / "product")
        self.assertEqual(copied["source_root"], str(product))
        self.assertEqual(copied["identity"], self.identity)
        self.assertEqual(binding["env"]["FOUNDRY_PRODUCT_ROOT"], str(root))
        self.assertNotIn(str(root), binding["write_roots"])
        self.assertNotIn(str(root), binding["areas"].values())
        self.assertFalse(root.is_relative_to(binding["areas"]["scratch"]))
        self.assertEqual((root / "src/reader.py").read_bytes(), (product / "src/reader.py").read_bytes())
        self.assertFalse((root / "unlisted.txt").exists())
        self.assertEqual((root / "run-check").stat().st_mode & 0o777, 0o555)
        for row in copied["files"]:
            self.assertEqual(row["source"], row["copy"])
            self.assertEqual((root / row["path"]).stat().st_mode & 0o222, 0)
            self.assertNotEqual((root / row["path"]).stat().st_ino, (product / row["path"]).stat().st_ino)
        for path in copied["write_roots"]:
            self.assertIn(path, binding["write_roots"])
            self.assertTrue(Path(path).is_dir())
        (root / ".cache/result").write_text("generated")
        self.assertFalse((product / ".cache").exists())
        self.assertEqual(validate_product_copy(binding)["status"], "UNCHANGED")

    def test_product_copy_validation_keeps_outputs_and_source_revision_separate(self):
        binding, product = self.product_binding()
        root = Path(binding["product_copy"]["root"])
        (root / "build/output/result.json").write_text("generated build output")
        (product / "src/reader.py").write_text("later source change, checked at controller acceptance")
        self.assertEqual(validate_product_copy(binding)["status"], "UNCHANGED")
        self.assertEqual(validate_product_copy_sources(binding, product)["status"], "CHANGED")
        self.assertIs(materialize_product_copy(binding, product), binding)
        self.assertEqual((root / "src/reader.py").read_text(), "VALUE = 'working tree content'\n")
        self.assertTrue((root / "build/output/result.json").exists())

    def test_product_copy_source_check_survives_cleanup_and_ignores_unlisted_files(self):
        binding, product = self.product_binding()
        original = deepcopy(binding)
        self.assertEqual(cleanup_resources(binding, True)["status"], "CLEANED")
        (product / "unlisted.txt").write_text("unrelated authorized edit")
        self.assertEqual(validate_product_copy_sources(binding, product)["status"], "UNCHANGED")
        self.assertFalse(Path(binding["product_copy"]["root"]).exists())
        self.assertEqual(binding, original)

    def test_product_copy_source_check_detects_changed_missing_or_rebound_declared_inputs(self):
        for mutation in ("bytes", "execute", "missing", "root"):
            with self.subTest(mutation=mutation):
                isolated = VerificationResourcesTests()
                isolated.setUp()
                self.addCleanup(isolated.doCleanups)
                binding, product = isolated.product_binding()
                target = product / "src/reader.py"
                if mutation == "bytes":
                    target.write_text("changed declared dependency")
                elif mutation == "execute":
                    target.chmod(0o755)
                elif mutation == "missing":
                    target.unlink()
                else:
                    binding["product_copy"]["source_root"] = str(isolated.base)
                result = validate_product_copy_sources(binding, product)
                self.assertEqual(result["status"], "CHANGED" if mutation in {"bytes", "execute"} else "UNAVAILABLE")
                self.assertNotIn(str(target), result["reason"])

    def test_product_copy_validation_detects_input_changes_and_never_rebuilds(self):
        for mutation in ("bytes", "execute", "missing", "symlink", "identity"):
            with self.subTest(mutation=mutation):
                isolated = VerificationResourcesTests()
                isolated.setUp()
                self.addCleanup(isolated.doCleanups)
                binding, product = isolated.product_binding()
                target = Path(binding["product_copy"]["root"]) / "src/reader.py"
                if mutation == "bytes":
                    target.chmod(0o644)
                    target.write_text("changed input")
                elif mutation == "execute":
                    target.chmod(0o555)
                elif mutation == "missing":
                    target.unlink()
                elif mutation == "symlink":
                    target.unlink()
                    target.symlink_to(product / "src/reader.py")
                else:
                    binding["product_copy"]["identity"]["command_id"] = "OTHER"
                result = validate_product_copy(binding)
                self.assertIn(result["status"], ("CHANGED", "UNAVAILABLE"))
                with self.assertRaises(RequestValidationError):
                    materialize_product_copy(binding, product)
                self.assertNotIn(str(target), result["reason"])

    def test_product_copy_validation_compares_execute_bits_not_write_mode(self):
        binding, _ = self.product_binding()
        target = Path(binding["product_copy"]["root"]) / "src/reader.py"
        target.chmod(0o644)
        self.assertEqual(validate_product_copy(binding)["status"], "UNCHANGED")

    def test_product_copy_rejects_link_directory_fifo_missing_inputs(self):
        for kind in ("symlink", "directory", "fifo", "missing"):
            with self.subTest(kind=kind):
                product = self.base / kind
                product.mkdir()
                source = product / "input"
                if kind == "symlink":
                    real = product / "real"
                    real.write_text("source")
                    source.symlink_to(real)
                elif kind == "directory":
                    source.mkdir()
                elif kind == "fifo":
                    os.mkfifo(source)
                self.config["profiles"]["sqlite"]["product_copy"] = {"files": ["input"], "writable_paths": ["out"]}
                binding = self.binding(command_id=kind)
                with self.assertRaises(RequestValidationError):
                    materialize_product_copy(binding, product)
                self.assertNotIn("product_copy", binding)

    def test_product_copy_clones_hardlinked_source_without_retaining_link_relation(self):
        product = self.base / "product"
        product.mkdir()
        (product / "source").write_text("working input")
        os.link(product / "source", product / "input")
        self.config["profiles"]["sqlite"]["product_copy"] = {"files": ["input"], "writable_paths": ["out"]}
        binding = self.binding()
        materialize_product_copy(binding, product)
        copied = Path(binding["product_copy"]["root"]) / "input"
        self.assertEqual(copied.stat().st_nlink, 1)
        self.assertNotEqual(copied.stat().st_ino, (product / "input").stat().st_ino)
        self.assertEqual(validate_product_copy(binding)["status"], "UNCHANGED")

    def test_product_copy_cleanup_retains_failure_and_only_removes_owned_leaf(self):
        binding, product = self.product_binding()
        copy_root = Path(binding["product_copy"]["root"])
        (copy_root / ".cache/output").write_text("generated")
        self.assertEqual(cleanup_resources(binding, False)["status"], "RETAINED")
        self.assertTrue(copy_root.exists())
        unrelated = self.base / "unrelated"
        unrelated.mkdir()
        (unrelated / "keep").write_text("untouched")
        (copy_root / ".cache/link").symlink_to(unrelated, target_is_directory=True)
        self.assertEqual(cleanup_resources(binding, True)["status"], "CLEANED")
        self.assertFalse(copy_root.exists())
        self.assertTrue((product / "src/reader.py").exists())
        self.assertTrue((unrelated / "keep").exists())
        self.assertEqual(cleanup_resources(binding, True)["status"], "CLEANED")
