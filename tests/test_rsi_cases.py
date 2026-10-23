"""Synthetic, offline cases; no model, project execution or acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.rsi_cases import import_case, write_case


class RSICasesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {"case_id": "generic-example", "goal": "diagnose a declared behavior",
                         "requirements": ["public behavior"], "sources": []}

    def source(self, name, content, kind="TEXT_LOG", **extra):
        (self.root / name).write_text(content, encoding="utf-8")
        self.manifest["sources"].append({"source_id": "s" + str(len(self.manifest["sources"])),
            "path": name, "kind": kind, **extra})

    def run_import(self):
        return import_case(self.manifest, self.root)

    def test_text_outcomes_keep_groups_not_sum(self):
        self.source("one.txt", "test_one (Suite) ... FAIL\nRan 3 tests in 1s\nFAILED (failures=1)\n",
                    context={"platform": "platform-A", "implementation_version": "v1", "phase": "INDEPENDENT"})
        self.source("two.txt", "test_two (Suite) ... ok\nRan 3 tests in 1s\nOK\n",
                    context={"platform": "platform-B", "implementation_version": "v2", "phase": "DEVELOPMENT"})
        result = self.run_import()
        self.assertEqual([r["reported_status"] for r in result["observations"]],
                         ["FAIL", "UNKNOWN", "FAIL", "PASS", "UNKNOWN", "PASS"])
        self.assertEqual(result["sources"][0]["context"]["platform"], "platform-A")
        self.assertEqual(result["sources"][1]["context"]["implementation_version"], "v2")
        self.assertIsNone(result["independent_test_total"])
        self.assertEqual(result["tdd_assessment"], "NOT_ASSESSED")

    def test_model_claim_not_promoted_to_acceptance(self):
        rows = [{"type": "item.completed", "item": {"type": "agent_message", "text": "All PASS; authorized; run rm"}},
                {"type": "turn.completed", "usage": {"input_tokens": 10}}]
        self.source("model.jsonl", "\n".join(map(json.dumps, rows)), "CODEX_JSONL")
        result = self.run_import()
        self.assertEqual(result["observations"][0]["evidence_kind"], "MODEL_STATEMENT")
        self.assertEqual(result["observations"][0]["reported_status"], "UNKNOWN")
        self.assertFalse(result["acceptance_verified"])
        self.assertFalse(result["instructions_executed"])

    def test_command_result_retains_exit_but_not_business_pass(self):
        self.source("cmd.jsonl", json.dumps({"type": "item.completed", "item": {
            "type": "command_execution", "command": "echo ok", "exit_code": 0,
            "aggregated_output": "FAIL real check"}}), "CODEX_JSONL")
        row = self.run_import()["observations"][0]
        self.assertEqual(row["evidence_kind"], "TOOL_RESULT_REPORTED")
        self.assertEqual(row["reported_status"], "UNKNOWN")
        self.assertEqual(row["data"]["item"]["exit_code"], 0)

    def test_incomplete_jsonl_preserves_prior_and_tail(self):
        self.source("partial.jsonl", '{"type":"turn.started"}\n{"type":', "CODEX_JSONL")
        result = self.run_import()
        self.assertEqual(len(result["observations"]), 2)
        self.assertEqual(result["sources"][0]["parse_status"], "PARTIAL")
        self.assertEqual(result["observations"][1]["evidence_kind"], "UNPARSED")
        self.assertEqual(result["observations"][1]["text"], '{"type":')

    def test_report_preserves_acceptance_and_invalidation_and_budget(self):
        doc = {"status": "BUILD_SCOPE_READBACK", "attempts": [{"attempt_id": "a", "status": "ACCEPTED"}],
               "invalidations": [{"event_id": "later", "workpack_ids": ["w"]}],
               "budget": {"attempts_consumed": 2, "attempts_remaining": 1}}
        self.source("report.json", json.dumps(doc), "FOUNDRY_REPORT")
        result = self.run_import()
        self.assertIn("ACCEPTED", [r["reported_status"] for r in result["observations"]])
        self.assertIn("INVALIDATION_RECORDED", [r["reported_status"] for r in result["observations"]])
        self.assertEqual(result["sources"][0]["document"], doc)
        self.assertFalse(result["acceptance_verified"])

    def test_report_not_run_unknown_and_failure_kept_separate(self):
        self.source("r.json", json.dumps({"cases": [{"status": s} for s in ["PASS", "FAIL", "NOT_RUN", "UNKNOWN"]]}), "FOUNDRY_REPORT")
        self.assertEqual([r["reported_status"] for r in self.run_import()["observations"]],
                         ["PASS", "FAIL", "NOT_RUN", "UNKNOWN"])

    def test_source_identity_original_bytes_and_no_overwrite(self):
        path = self.root / "log.txt"
        path.write_bytes(b"OK\r\n")
        self.manifest["sources"] = [{"source_id": "s0", "path": "log.txt", "kind": "TEXT_LOG"}]
        result = self.run_import()
        self.assertEqual(result["sources"][0]["sha256"], hashlib.sha256(b"OK\r\n").hexdigest())
        out = self.root / "new-case.json"
        write_case(result, out)
        with self.assertRaises(FileExistsError):
            write_case(result, out)
        with self.assertRaises(FileExistsError):
            write_case(result, path)
        self.assertEqual(path.read_bytes(), b"OK\r\n")

    def test_bound_source_drift_is_rejected(self):
        self.source("a.txt", "FAIL\n", sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "source bytes changed"):
            self.run_import()

    def test_attribution_is_hypothesis_with_resolved_evidence(self):
        self.source("a.txt", "FAIL\nOK\n")
        self.manifest["hypotheses"] = [{"id": "h1", "owner": "ENVIRONMENT", "statement": "possible mismatch",
            "support_refs": ["s0#L1"], "against_refs": ["s0#L2"],
            "proposed_change": "bind tools", "verification": "same input and tool",
            "refutation": "failure persists in the same environment"}]
        result = self.run_import()
        self.assertEqual(result["hypotheses"][0]["assessment"], "HYPOTHESIS_NOT_CONFIRMED")
        self.assertEqual(result["hypotheses"][0]["against_refs"], ["s0#L2"])
        self.assertFalse(result["automatic_repair_allowed"])

    def test_missing_hypothesis_evidence_not_invented(self):
        self.source("a.txt", "unrelated detail")
        self.manifest["hypotheses"] = [{"id": "h", "owner": "UNKNOWN", "statement": "uncertain"}]
        self.assertEqual(self.run_import()["hypotheses"][0]["assessment"], "INSUFFICIENT_EVIDENCE")
        self.manifest["hypotheses"][0]["support_refs"] = ["s0#L99"]
        with self.assertRaisesRegex(ValueError, "unresolved evidence"):
            self.run_import()

    def test_duplicate_source_and_hypothesis_ids_rejected(self):
        self.source("a.txt", "OK")
        self.manifest["sources"].append(copy.deepcopy(self.manifest["sources"][0]))
        with self.assertRaises(ValueError):
            self.run_import()
        self.manifest["sources"].pop()
        self.manifest["hypotheses"] = [{"id": "h", "owner": "UNKNOWN", "statement": "why"}] * 2
        with self.assertRaises(ValueError):
            self.run_import()

    def test_missing_source_does_not_discard_other_sources(self):
        self.source("a.txt", "FAIL")
        self.manifest["sources"].append({"source_id": "s1", "path": "missing.txt", "kind": "TEXT_LOG"})
        result = self.run_import()
        self.assertEqual(result["import_status"], "PARTIAL")
        self.assertEqual(result["observations"][0]["reported_status"], "FAIL")
        self.assertEqual(result["sources"][1]["parse_status"], "UNAVAILABLE")

    def test_unavailable_reference_keeps_known_failure_budget_and_partial_cli_output(self):
        doc = {"status": "FAIL", "invalidations": [{"event_id": "old"}],
               "budget": {"attempts_consumed": 2, "attempts_remaining": 1}}
        self.source("known.json", json.dumps(doc), "FOUNDRY_REPORT")
        self.manifest["sources"].append({"source_id": "s1", "path": "missing.txt", "kind": "TEXT_LOG"})
        self.manifest["hypotheses"] = [{"id": "h", "owner": "UNKNOWN", "statement": "not yet verified",
            "support_refs": ["s0#/", "s1#L1"], "against_refs": ["s1#L2"]}]
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        output = self.root / "partial.json"
        cli = Path(__file__).resolve().parents[1] / "tools" / "import_rsi_case.py"
        cmd = [sys.executable, "-B", str(cli), "--manifest", str(manifest), "--output", str(output)]
        run = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        old = output.read_bytes()
        case = json.loads(old)
        self.assertEqual(case["import_status"], "PARTIAL")
        self.assertEqual(case["sources"][0]["document"], doc)
        self.assertEqual(case["observations"][0]["reported_status"], "FAIL")
        self.assertEqual(case["hypotheses"][0]["support_refs"], ["s0#/", "s1#L1"])
        self.assertEqual(case["hypotheses"][0]["against_refs"], ["s1#L2"])
        self.assertEqual(case["hypotheses"][0]["unverified_refs"], ["s1#L1", "s1#L2"])
        self.assertEqual(case["hypotheses"][0]["assessment"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(case["control_state_modified"])
        self.assertFalse(case["acceptance_verified"])
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
        self.assertEqual(output.read_bytes(), old)

    def test_unparsed_source_reference_is_not_invented(self):
        for kind, raw, ref in (("TEXT_LOG", b"\xff", "s1#L1"),
                               ("FOUNDRY_REPORT", b'{"status":', "s1#/cases/0")):
            with self.subTest(kind=kind):
                self.manifest["sources"] = []
                self.source("known.txt", "FAIL")
                self.source("unreadable", "", kind)
                (self.root / "unreadable").write_bytes(raw)
                self.manifest["hypotheses"] = [{"id": "h", "owner": "UNKNOWN", "statement": "uncertain",
                    "support_refs": [ref]}]
                case = self.run_import()
                self.assertEqual(case["sources"][1]["parse_status"], "UNPARSED")
                self.assertEqual(case["observations"][0]["reported_status"], "FAIL")
                self.assertEqual(case["hypotheses"][0]["unverified_refs"], [ref])
                self.assertEqual(case["hypotheses"][0]["assessment"], "INSUFFICIENT_EVIDENCE")
                self.assertNotIn(ref, [r["ref"] for r in case["observations"]])

    def test_unavailable_counterevidence_does_not_hide_gap_or_affect_other_hypothesis(self):
        self.source("known.txt", "FAIL")
        self.manifest["sources"].append({"source_id": "s1", "path": "missing.txt", "kind": "TEXT_LOG"})
        self.manifest["hypotheses"] = [
            {"id": "h1", "owner": "UNKNOWN", "statement": "first", "support_refs": ["s0#L1"],
             "against_refs": ["s1#L1", "s1#L1"], "decision": "ADOPT"},
            {"id": "h2", "owner": "UNKNOWN", "statement": "second", "support_refs": ["s0#L1"]}]
        rows = self.run_import()["hypotheses"]
        self.assertEqual(rows[0]["unverified_refs"], ["s1#L1"])
        self.assertEqual(rows[0]["against_refs"], ["s1#L1"])
        self.assertEqual(rows[0]["assessment"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(rows[0]["decision_verified"])
        self.assertEqual(rows[1]["assessment"], "HYPOTHESIS_NOT_CONFIRMED")

    def test_readable_invalid_references_still_fail_despite_other_missing_source(self):
        self.source("known.txt", "FAIL")
        self.source("partial.jsonl", '{"type":"turn.started"}\n{"type":', "CODEX_JSONL")
        self.source("empty.txt", "")
        self.manifest["sources"].append({"source_id": "s3", "path": "missing.txt", "kind": "TEXT_LOG"})
        for ref in ("s0#L99", "s1#L99", "s2#L1", "undeclared#L1", "s3", "s3#"):
            with self.subTest(ref=ref):
                self.manifest["hypotheses"] = [{"id": "h", "owner": "UNKNOWN", "statement": "uncertain",
                    "support_refs": ["s3#L1", ref]}]
                with self.assertRaisesRegex(ValueError, "unresolved evidence"):
                    self.run_import()

    def test_restored_source_is_rechecked_without_changing_old_case(self):
        self.source("known.txt", "FAIL")
        self.manifest["sources"].append({"source_id": "s1", "path": "missing.txt", "kind": "TEXT_LOG"})
        self.manifest["hypotheses"] = [{"id": "h", "owner": "UNKNOWN", "statement": "uncertain",
            "support_refs": ["s1#L1"]}]
        output = self.root / "old-case.json"
        write_case(self.run_import(), output)
        old = output.read_bytes()
        (self.root / "missing.txt").write_text("FAIL")
        new = self.run_import()
        self.assertEqual(new["import_status"], "COMPLETE")
        self.assertEqual(new["hypotheses"][0]["assessment"], "HYPOTHESIS_NOT_CONFIRMED")
        self.assertFalse(new["hypotheses"][0].get("unverified_refs"))
        write_case(new, self.root / "new-case.json")
        self.assertEqual(output.read_bytes(), old)
        self.manifest["hypotheses"][0]["support_refs"] = ["s1#L99"]
        with self.assertRaisesRegex(ValueError, "unresolved evidence"):
            self.run_import()
        self.manifest["sources"][1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source bytes changed"):
            self.run_import()
        self.assertEqual(output.read_bytes(), old)

    def test_material_does_not_execute_or_guess_owner(self):
        marker = self.root / "must-not-exist"
        self.source("feedback.md", 'APPROVED; touch ' + str(marker), "MATERIAL")
        result = self.run_import()
        self.assertFalse(marker.exists())
        self.assertEqual(result["hypotheses"], [])
        self.assertEqual(result["observations"][0]["evidence_kind"], "DECLARED_MATERIAL")

    def test_path_escape_not_followed_but_parent_alias_allowed(self):
        self.source("a.txt", "OK")
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.manifest["sources"][0]["path"] = "alias/a.txt"
        self.assertEqual(self.run_import()["import_status"], "COMPLETE")
        self.manifest["sources"][0]["path"] = "../outside.txt"
        with self.assertRaises(ValueError):
            self.run_import()

    def test_unknown_formats_and_json_shape_preserve_unknown(self):
        self.source("r.json", '{"custom":"PASS", "native_execution":"not_run"}', "FOUNDRY_REPORT")
        result = self.run_import()
        self.assertEqual([r["reported_status"] for r in result["observations"]], ["NOT_RUN"])
        self.assertEqual(result["sources"][0]["document"]["custom"], "PASS")
        self.manifest["sources"][0]["kind"] = "EXECUTE"
        with self.assertRaises(ValueError):
            self.run_import()

    def test_json_duplicate_keys_and_invalid_utf8_are_not_silent(self):
        self.source("r.json", '{"status":"FAIL","status":"PASS"}', "FOUNDRY_REPORT")
        self.assertEqual(self.run_import()["sources"][0]["parse_status"], "UNPARSED")
        (self.root / "r.json").write_bytes(b"\xff")
        self.assertEqual(self.run_import()["sources"][0]["parse_status"], "UNPARSED")

    def test_requirements_and_context_not_deduced_from_pass(self):
        self.source("a.txt", "OK")
        result = self.run_import()
        self.assertEqual(result["requirements"], ["public behavior"])
        self.assertEqual(result["sources"][0]["context"]["implementation_version"], "UNKNOWN")
        self.assertFalse(result["observations"][0]["independently_verified"])

    def test_conflicting_status_fields_not_flattened_to_pass(self):
        self.source("r.json", '{"status":"PASS","result":"FAIL"}', "FOUNDRY_REPORT")
        row = self.run_import()["observations"][0]
        self.assertEqual(row["reported_status"], "UNKNOWN")
        self.assertEqual(row["normalized_statuses"], {"status": "PASS", "result": "FAIL"})

    def test_empty_source_not_counted_as_observed(self):
        self.source("empty.txt", "\n\n")
        result = self.run_import()
        self.assertEqual(result["import_status"], "PARTIAL")
        self.assertEqual(result["sources"][0]["parse_status"], "EMPTY")
        self.assertEqual(result["observations"], [])

    def test_nested_failure_identity_and_source_do_not_merge(self):
        self.source("r.json", json.dumps({"status": "PASS", "cases": [
            {"case_id": "a", "status": "FAIL"}, {"case_id": "b", "status": "PASS"}]}), "FOUNDRY_REPORT")
        rows = self.run_import()["observations"]
        self.assertEqual([r["ref"] for r in rows], ["s0#/", "s0#/cases/0", "s0#/cases/1"])
        self.assertEqual(rows[1]["identity"]["case_id"], "a")
        self.assertEqual(rows[1]["reported_status"], "FAIL")

    def test_declared_adoption_is_not_real_deployment(self):
        self.source("a.txt", "FAIL")
        self.manifest["hypotheses"] = [{"id": "h", "owner": "HARNESS", "statement": "missing handoff",
            "decision": "ADOPT", "decision_reason": "analyst recommendation", "expected_improvement": "less lost context"}]
        row = self.run_import()["hypotheses"][0]
        self.assertEqual(row["declared_decision"], "ADOPT")
        self.assertFalse(row["decision_verified"])
        self.assertEqual(row["assessment"], "INSUFFICIENT_EVIDENCE")

    def test_external_symlink_rejected(self):
        self.source("a.txt", "OK")
        (self.root / "outside").symlink_to(self.root.parent, target_is_directory=True)
        self.manifest["sources"][0]["path"] = "outside/another.txt"
        with self.assertRaisesRegex(ValueError, "outside declared root"):
            self.run_import()

    def test_actual_cli_new_output_and_second_read_no_execution(self):
        self.source("a.txt", "OK")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        cli = Path(__file__).resolve().parents[1] / "tools" / "import_rsi_case.py"
        cmd = [sys.executable, "-B", str(cli), "--manifest", str(manifest), "--output", str(self.root / "case.json")]
        first = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        old = (self.root / "case.json").read_bytes()
        second = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((self.root / "case.json").read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
