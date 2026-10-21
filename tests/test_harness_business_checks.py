"""Synthetic checker tests, not delivered business runs or real host reviews."""
import contextlib
from copy import deepcopy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "examples/harness-composition-upgrade"
SPEC = importlib.util.spec_from_file_location("business_checks", ROOT / "verifier/check_business.py")
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class BusinessCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / "outputs"
        self.target.mkdir()
        self.protected = self.root / "protected"
        self.protected.mkdir()

    def fixture(self, group):
        directory = "market-research" if group == "market-live" else group
        target = self.protected / "business" / directory
        if not target.exists():
            shutil.copytree(ROOT / "business" / directory, target)
        return target

    def product(self, group, version):
        fixture = self.fixture(group)
        manifest = read(fixture / "manifest.json")
        names = CHECKS.output_names(manifest, group, version)
        for name in names:
            (self.target / name).write_text("Synthetic checker-test output. Not a business result.\n", encoding="utf-8")
        if group == "prd-design":
            expected = read(fixture / "expected.json")
            trace = {"requirements": [{"id": row["id"], "prd_section": "section-" + row["id"], "prototype_refs": ["view-" + row["id"]]} for row in expected["requirements"]],
                     "states": expected["required_states"], "view_widths": [375, 1280], "customization": read(fixture / "inputs/user-customization.json")}
            write(self.target / "traceability.json", trace)
            if version == "v2":
                edges = [("offline_draft", "pending_user_retry"), ("pending_user_retry", "submitting"), ("submitting", "confirmed"), ("submitting", "capacity_conflict"), ("capacity_conflict", "selection")]
                write(self.target / "state-transitions.json", {"transitions": [{"from": start, "action": "test action", "condition": "test condition", "to": end, "preserves_contact_draft": True, "reservation_created": end == "confirmed"} for start, end in edges]})
        elif group == "data-reasoning":
            (self.target / "normalized-orders.csv").write_text(
                "event_id,revision,local_time,channel,amount_yuan\n"
                "b001,1,2026-09-01T00:30:00+08:00,web,12.00\n"
                "b002,2,2026-09-01T10:00:00+08:00,desk,25.00\n"
                "b004,1,2026-09-01T15:00:00+08:00,desk,\n"
                "b005,1,2026-09-01T23:50:00+08:00,web,35.00\n"
                "b008,1,2026-09-01T22:20:00+08:00,web,8.50\n", encoding="utf-8")
            metrics = {"eligible_paid_count": 5, "known_amount_count": 4, "unknown_amount_count": 1,
                       "known_revenue_yuan": "80.50", "amount_coverage": "0.8", "known_amount_mean_exact_yuan": "20.125",
                       "known_amount_mean_display_yuan": "20.13", "complete_revenue_yuan": None, "complete_mean_yuan": None, "growth_rate": None,
                       "customization": read(fixture / "inputs/user-customization.json"), "definition": read(fixture / "inputs/metric-definition.json")}
            if version == "v2":
                metrics["groups"] = {"web": {"eligible_paid_count": 3, "known_amount_count": 3, "known_revenue_yuan": "55.50"},
                                     "desk": {"eligible_paid_count": 2, "known_amount_count": 1, "known_revenue_yuan": "25.00"}}
                write(self.target / "sensitivity.json", {"cap_yuan": "40.00", "assumption": "Synthetic conditional assumption, not observed.", "revenue_min_yuan": "80.50", "revenue_max_yuan": "120.50", "all_paid_mean_min_yuan": "16.10", "all_paid_mean_max_yuan": "24.10", "is_actual_complete_revenue": False})
            write(self.target / "metrics.json", metrics)
        elif group == "market-research":
            sources = read(fixture / "inputs/sources.json")["sources"]
            write(self.target / "source-register.json", {"synthetic": True, "sources": sources})
            write(self.target / "claims.json", {"scope": read(fixture / "inputs/research-scope.json"),
                  "observations": [{"id": "M01", "statement": "Synthetic historical interest only", "numerator": 35, "denominator": 100, "ratio": "0.35", "citations": ["S01:P1", "S01:P2"]},
                                   {"id": "M02", "statement": "Synthetic volunteer free use only", "numerator": 28, "denominator": 40, "ratio": "0.70", "citations": ["S02:P1", "S02:P2"]}],
                  "price_conflict": {"citations": ["S03:P1", "S04:P1"], "values_yuan": ["29", "39"], "resolution": "unknown"}, "unsupported_claims": ["M04", "M05", "M06"]})
        else:
            sources = []
            for index in (1, 2):
                sources.append({"product": "Synthetic unit-test product " + str(index), "query": "test-only query", "url": "https://example.invalid/tool" + str(index),
                                "title": "Synthetic test page", "search_tool_ref": "fixture-search", "open_tool_ref": "fixture-open", "retrieved_at": "2026-10-15T10:00:00+08:00",
                                "published_at": None, "updated_at": None, "currency": None, "billing_period": None, "tax": None, "region": None,
                                "claims": {"feature": {"value": "Test scheduling", "excerpt": "Synthetic excerpt", "location": "Test paragraph"},
                                           "price": {"value": None, "unknown_reason": "Not present in synthetic page"}, "trial": {"value": None, "unknown_reason": "Not present in synthetic page"}}})
            write(self.target / "live-source-register.json", {"as_of": "2026-10-15", "sources": sources})
        return fixture, names

    def host(self, group, version, names):
        evidence = self.protected / "host-evidence"
        evidence.mkdir(exist_ok=True)
        snapshot = evidence / "reviewed-output"
        snapshot.mkdir(exist_ok=True)
        for name in names:
            shutil.copyfile(self.target / name, snapshot / name)
        shutil.copyfile(self.fixture(group) / "workflows" / (version + ".md"), evidence / "workflow.md")
        (evidence / "test-observation.txt").write_text("Synthetic unit-test observation. Not real execution, visual or search evidence.\n")
        ids = ["workflow-execution", *CHECKS.HOST_OBLIGATIONS[group], *(["upgrade-recheck"] if version == "v2" else [])]
        write(evidence / "review.json", {"group": group, "version": version, "reviewer": "synthetic-test-reviewer", "reviewed_outputs": "reviewed-output", "workflow_file": "workflow.md",
                                        "observations": [{"id": key, "result": "PASS", "reason": "Synthetic test of record consumption only", "evidence_refs": ["test-observation.txt"]} for key in ids]})
        return evidence

    def automatic(self, group, version="v1"):
        return CHECKS.automatic(group, version, self.target, self.fixture(group))

    def test_all_automatic_shapes_are_checkable_without_network_or_product_execution(self):
        with patch("socket.socket", side_effect=AssertionError("no network")), patch("subprocess.Popen", side_effect=AssertionError("no product execution")):
            for group in CHECKS.HOST_OBLIGATIONS:
                for version in ("v1", "v2"):
                    with self.subTest(group=group, version=version):
                        _, names = self.product(group, version)
                        self.assertEqual(self.automatic(group, version), names)

    def test_prd_missing_requirement_state_customization_and_v2_transition_fail(self):
        for mutation in ("requirement", "state", "customization", "transition"):
            with self.subTest(mutation=mutation):
                self.product("prd-design", "v2")
                path = self.target / "traceability.json"
                trace = read(path)
                if mutation == "requirement":
                    trace["requirements"] = [r for r in trace["requirements"] if r["id"] != "R03"]
                elif mutation == "state":
                    trace["states"].remove("network_error")
                elif mutation == "customization":
                    trace["customization"]["brand_color"] = "#FFFFFF"
                else:
                    transitions = read(self.target / "state-transitions.json")
                    transitions["transitions"].pop(0)
                    write(self.target / "state-transitions.json", transitions)
                write(path, trace)
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("prd-design", "v2")

    def test_prd_confirmed_can_clear_draft_but_retry_must_preserve_it(self):
        _, names = self.product("prd-design", "v2")
        path = self.target / "state-transitions.json"
        transitions = read(path)
        confirmed = next(row for row in transitions["transitions"] if row["to"] == "confirmed")
        confirmed["preserves_contact_draft"] = False
        write(path, transitions)
        self.assertEqual(self.automatic("prd-design", "v2"), names)

        for start, end in (("offline_draft", "pending_user_retry"), ("pending_user_retry", "submitting"),
                           ("submitting", "capacity_conflict"), ("capacity_conflict", "selection")):
            with self.subTest(start=start, end=end):
                invalid = deepcopy(transitions)
                retry = next(row for row in invalid["transitions"] if row["from"] == start and row["to"] == end)
                retry["preserves_contact_draft"] = False
                write(path, invalid)
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("prd-design", "v2")

    def test_prd_additional_user_clear_actions_do_not_invalidate_recovery_routes(self):
        _, names = self.product("prd-design", "v2")
        path = self.target / "state-transitions.json"
        baseline = read(path)
        for action in ("用户主动清除", "Discard local entries", "command-17"):
            with self.subTest(action=action):
                transitions = deepcopy(baseline)
                for row in transitions["transitions"]:
                    row["action"] = "alternative operation label"
                for start, end in (("offline_draft", "offline_draft"), ("pending_user_retry", "selection"),
                                   ("capacity_conflict", "selection")):
                    transitions["transitions"].append({"from": start, "action": action,
                        "condition": "The user explicitly requests clearing the local entries.", "to": end,
                        "preserves_contact_draft": False, "reservation_created": False})
                write(path, transitions)
                self.assertEqual(self.automatic("prd-design", "v2"), names)

    def test_prd_an_unrelated_preserving_edge_does_not_replace_required_recovery(self):
        self.product("prd-design", "v2")
        path = self.target / "state-transitions.json"
        transitions = read(path)
        recovery = next(row for row in transitions["transitions"]
                        if (row["from"], row["to"]) == ("capacity_conflict", "selection"))
        recovery["preserves_contact_draft"] = False
        transitions["transitions"].append({**recovery, "action": "another non-preserving action"})
        transitions["transitions"].append({**recovery, "to": "offline_draft", "preserves_contact_draft": True})
        write(path, transitions)
        with self.assertRaises(CHECKS.BusinessFailure):
            self.automatic("prd-design", "v2")

    def test_prd_nonconfirmed_transitions_cannot_create_a_reservation(self):
        self.product("prd-design", "v2")
        path = self.target / "state-transitions.json"
        baseline = read(path)
        for index, row in enumerate(baseline["transitions"]):
            if row["to"] == "confirmed":
                continue
            with self.subTest(start=row["from"], end=row["to"]):
                transitions = deepcopy(baseline)
                transitions["transitions"][index]["reservation_created"] = True
                write(path, transitions)
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("prd-design", "v2")

    def test_data_recomputes_numbers_denominators_and_missing_semantics(self):
        for key, bad in [("known_revenue_yuan", "100.50"), ("complete_revenue_yuan", "80.50"), ("known_amount_mean_display_yuan", "16.10"), ("growth_rate", "0.20"), ("unknown_amount_count", True)]:
            with self.subTest(key=key):
                self.product("data-reasoning", "v1")
                path = self.target / "metrics.json"
                metrics = read(path)
                metrics[key] = bad
                write(path, metrics)
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("data-reasoning")

    def test_data_wrong_detail_and_conditional_bounds_fail(self):
        for mutation in ("duplicate", "date", "missing_zero", "group", "bound", "observed"):
            with self.subTest(mutation=mutation):
                self.product("data-reasoning", "v2")
                path = self.target / "normalized-orders.csv"
                contents = path.read_text()
                if mutation == "duplicate":
                    path.write_text(contents + contents.splitlines()[1] + "\n")
                elif mutation == "date":
                    path.write_text(contents.replace("2026-09-01T00:30:00+08:00", "2026-08-31T16:30:00+00:00"))
                elif mutation == "missing_zero":
                    path.write_text(contents.replace("+08:00,desk,\n", "+08:00,desk,0\n"))
                elif mutation == "group":
                    value = read(self.target / "metrics.json")
                    value["groups"]["desk"]["known_amount_count"] = 2
                    write(self.target / "metrics.json", value)
                else:
                    value = read(self.target / "sensitivity.json")
                    value["revenue_max_yuan" if mutation == "bound" else "is_actual_complete_revenue"] = "999" if mutation == "bound" else True
                    write(self.target / "sensitivity.json", value)
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("data-reasoning", "v2")

    def test_data_local_time_accepts_equivalent_iso_precision(self):
        for version in ("v1", "v2"):
            for local_time in ("2026-09-01T00:30:00+08:00", "2026-09-01T00:30:00.000000+08:00"):
                with self.subTest(version=version, local_time=local_time):
                    _, names = self.product("data-reasoning", version)
                    path = self.target / "normalized-orders.csv"
                    path.write_text(path.read_text().replace("2026-09-01T00:30:00+08:00", local_time))
                    self.assertEqual(self.automatic("data-reasoning", version), names)

    def test_data_local_time_rejects_unconverted_naive_or_different_time(self):
        for local_time in ("2026-08-31T16:30:00Z", "2026-09-01T00:30:00", "2026-09-01T00:30:00.000001+08:00", "not-a-time"):
            with self.subTest(local_time=local_time):
                self.product("data-reasoning", "v1")
                path = self.target / "normalized-orders.csv"
                path.write_text(path.read_text().replace("2026-09-01T00:30:00+08:00", local_time))
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("data-reasoning")

    def test_changed_protected_hand_calculation_is_not_a_product_failure(self):
        fixture, _ = self.product("data-reasoning", "v1")
        expected = read(fixture / "expected.json")
        expected["metrics"]["known_revenue_yuan"] = "999"
        write(fixture / "expected.json", expected)
        with self.assertRaises(CHECKS.EvidenceUnavailable):
            self.automatic("data-reasoning")

    def test_market_counts_citation_conflict_and_scope_are_not_just_file_presence(self):
        for mutation in ("ratio", "citation", "price", "resolution", "scope"):
            with self.subTest(mutation=mutation):
                self.product("market-research", "v1")
                claims = read(self.target / "claims.json")
                if mutation == "ratio":
                    claims["observations"][0]["ratio"] = "0.70"
                elif mutation == "citation":
                    claims["observations"][0]["citations"] = ["S01:P999"]
                elif mutation == "price":
                    claims["price_conflict"]["values_yuan"] = ["29"]
                elif mutation == "resolution":
                    claims["price_conflict"]["resolution"] = "29 is current"
                else:
                    claims["scope"]["region"] = "all markets"
                write(self.target / "claims.json", claims)
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("market-research")

    def test_live_records_do_not_accept_fixed_sources_or_missing_original_open(self):
        for mutation in ("url", "open", "date", "as_of", "feature"):
            with self.subTest(mutation=mutation):
                self.product("market-live", "v1")
                register = read(self.target / "live-source-register.json")
                row = register["sources"][0]
                if mutation == "url":
                    row["url"] = "fixture://S01"
                elif mutation == "open":
                    row["open_tool_ref"] = ""
                elif mutation == "date":
                    row["retrieved_at"] = "2026-10-15T10:00:00"
                elif mutation == "as_of":
                    register["as_of"] = "2026-10-15T10:00:00+08:00"
                else:
                    row["claims"]["feature"] = {"value": None, "unknown_reason": "not inspected"}
                write(self.target / "live-source-register.json", register)
                with self.assertRaises(CHECKS.BusinessFailure):
                    self.automatic("market-live")

    def test_live_utc_cross_day_is_valid_and_actual_run_date_is_host_checked(self):
        fixture, names = self.product("market-live", "v1")
        register = read(self.target / "live-source-register.json")
        # October 15 in Shanghai can be October 14 in a tool's UTC timestamp.
        register["sources"][0]["retrieved_at"] = "2026-10-14T18:30:00Z"
        write(self.target / "live-source-register.json", register)
        self.assertEqual(self.automatic("market-live"), names)

        # Structurally valid dates do not prove this is the recorded execution.
        register["sources"][0]["retrieved_at"] = "2024-05-15T10:00:00+08:00"
        write(self.target / "live-source-register.json", register)
        self.assertEqual(self.automatic("market-live"), names)
        evidence = self.host("market-live", "v1", names)
        review = read(evidence / "review.json")
        observation = next(row for row in review["observations"] if row["id"] == "claim-support-and-dates")
        observation.update(result="FAIL", reason="Synthetic counterexample: retrieval is from an earlier run, not this execution day.")
        write(evidence / "review.json", review)
        with self.assertRaises(CHECKS.BusinessFailure):
            CHECKS.reviewed("market-live", "v1", self.target, fixture, evidence, names)

    def test_reviewed_consumes_all_group_versions_with_exact_snapshots(self):
        for group in CHECKS.HOST_OBLIGATIONS:
            for version in ("v1", "v2"):
                with self.subTest(group=group, version=version):
                    fixture, names = self.product(group, version)
                    evidence = self.host(group, version, names)
                    CHECKS.reviewed(group, version, self.target, fixture, evidence, names)

    def test_reviewed_missing_unknown_and_stale_evidence_are_infrastructure_errors(self):
        for mutation in ("absent", "unfinished", "missing_file", "stale_output", "old_workflow", "missing_obligation"):
            with self.subTest(mutation=mutation):
                fixture, names = self.product("prd-design", "v2")
                evidence = self.host("prd-design", "v2", names)
                review = read(evidence / "review.json")
                if mutation == "unfinished":
                    review["observations"][0]["result"] = "NOT_RUN"
                elif mutation == "missing_file":
                    review["observations"][0]["evidence_refs"] = ["not-there.png"]
                elif mutation == "stale_output":
                    (self.target / "prototype.html").write_text("changed prototype")
                elif mutation == "old_workflow":
                    (evidence / "workflow.md").write_text("previous version")
                elif mutation == "missing_obligation":
                    review["observations"].pop()
                write(evidence / "review.json", review)
                with self.assertRaises(CHECKS.EvidenceUnavailable):
                    CHECKS.reviewed("prd-design", "v2", self.target, fixture, None if mutation == "absent" else evidence, names)

    def test_semantically_bad_text_can_pass_automatic_but_independent_review_rejects(self):
        for group, filename, obligation, bad_text in [
            ("prd-design", "prd.md", "original-requirements", "Offline save is already a confirmed reservation."),
            ("data-reasoning", "analysis.md", "reasoning-boundaries", "Promotion caused revenue growth of 20%."),
            ("market-research", "research.md", "claim-support-and-conflicts", "Demand doubled from 35% to 70%."),
            ("market-live", "live-research.md", "search-and-original-pages", "These synthetic test URLs prove real web research.")]:
            with self.subTest(group=group):
                fixture, names = self.product(group, "v1")
                (self.target / filename).write_text(bad_text)
                self.automatic(group)
                evidence = self.host(group, "v1", names)
                review = read(evidence / "review.json")
                row = next(row for row in review["observations"] if row["id"] == obligation)
                row.update(result="FAIL", reason="Synthetic counterexample: " + bad_text)
                write(evidence / "review.json", review)
                with self.assertRaises(CHECKS.BusinessFailure):
                    CHECKS.reviewed(group, "v1", self.target, fixture, evidence, names)

    def invoke(self, group="data-reasoning", phase="automatic", evidence=None, fixture=None):
        reports = self.root / "reports"
        reports.mkdir(exist_ok=True)
        args = ["--group", group, "--version", "v1", "--phase", phase, "--target", str(self.target), "--fixture", str((fixture or self.fixture(group)) / "manifest.json")]
        if evidence is not None:
            args += ["--host-evidence", str(evidence / "review.json")]
        env = {"FOUNDRY_CASE_ID": "TEST-CASE", "FOUNDRY_COMMAND_ID": "TEST-COMMAND", "FOUNDRY_REPORT_DIR": str(reports), "FOUNDRY_VERIFIER_ROOT": str(self.protected)}
        with patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            code = CHECKS.main(args)
        return code, read(reports / "summary.json")

    def test_structured_report_distinguishes_automatic_reviewed_assertion_and_missing_evidence(self):
        _, names = self.product("data-reasoning", "v1")
        code, report = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report["checks"], [{"id": "business-automatic", "status": "PASS"}])
        self.assertFalse(report["business_acceptance"])
        code, report = self.invoke(phase="reviewed")
        self.assertEqual(code, 2)
        self.assertEqual(report["checks"][0]["status"], "ERROR")
        self.assertNotIn("failure_kind", report)
        evidence = self.host("data-reasoning", "v1", names)
        code, report = self.invoke(phase="reviewed", evidence=evidence)
        self.assertEqual(code, 0)
        self.assertTrue(report["business_acceptance"])
        review = read(evidence / "review.json")
        review["observations"][1].update(result="FAIL", reason="Synthetic known calculation-execution failure")
        write(evidence / "review.json", review)
        code, report = self.invoke(phase="reviewed", evidence=evidence)
        self.assertEqual(code, 1)
        self.assertEqual(report["failure_kind"], "ASSERTION")
        self.assertEqual(report["errors"], [])
        self.assertFalse(report["business_acceptance"])

    def test_cli_requires_protected_file_anchors_without_development_fallback(self):
        self.product("data-reasoning", "v1")
        code, report = self.invoke(fixture=ROOT / "business/data-reasoning")
        self.assertEqual(code, 2)
        self.assertIn("protected verifier copy", report["errors"][0])
        (self.fixture("data-reasoning") / "expected.json").unlink()
        code, report = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn("cannot read JSON", report["errors"][0])


if __name__ == "__main__":
    unittest.main()
