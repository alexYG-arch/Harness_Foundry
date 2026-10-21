"""DATA package engineering fixtures, not real DATA business acceptance."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.verification_resources import validate_structured_result


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples/capability-adapters/packages/data-summary/1"


def fraction(numerator, denominator=1):
    return {"numerator": str(numerator), "denominator": str(denominator)}


def value(display, numerator, denominator, unit):
    return {"value": display, "exact": fraction(numerator, denominator), "unit": unit}


class CapabilityDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="capability-data-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.package = self.root / "delivered-capability"
        shutil.copytree(PACKAGE, self.package)
        self.source = self.root / "input.csv"
        self.config_path = self.root / "project.json"
        self.output = self.root / "result.json"
        self.expected = self.root / "expected.json"
        self.report = self.root / "report.json"
        self.source.write_text("item,team,amount,unit,stage\na,north,0.10,yuan,yes\nb,north,25,fen,yes\nc,south,broken,bad,no\n", encoding="utf-8")
        self.config = {
            "schema_version": "1.0", "group_by": ["team"],
            "filters": [{"column": "stage", "equals": "yes"}],
            "rows": {"key": ["item"], "duplicates": "error", "missing": "error"},
            "metrics": [
                {"id": "amount", "op": "sum", "column": "amount", "unit_column": "unit", "unit_factors": {"yuan": "1", "fen": "0.01"}, "unit": "yuan", "scale": 2, "rounding": "HALF_EVEN"},
                {"id": "count", "op": "count", "unit": "items", "scale": 0, "rounding": "DOWN"},
                {"id": "average", "op": "ratio", "numerator": "amount", "denominator": "count", "zero_denominator": "error", "unit": "yuan/item", "scale": 2, "rounding": "HALF_UP"},
            ],
        }
        # Independently specified test oracle: 0.10 + 25/100 = 7/20;
        # 7/20 divided by two records = 7/40 = 0.175 -> 0.18 HALF_UP.
        self.oracle = {
            "schema_version": "1.0", "summary": {"input_rows": 3, "included_rows": 2, "excluded_rows": 1},
            "groups": [{"key": {"team": "north"}, "metrics": {
                "amount": value("0.35", 7, 20, "yuan"), "count": value("2", 2, 1, "items"), "average": value("0.18", 7, 40, "yuan/item")}}],
            "rows": [
                {"record": 1, "group": {"team": "north"}, "key": {"item": "a"}, "contributions": {"amount": fraction(1, 10), "count": fraction(1)}},
                {"record": 2, "group": {"team": "north"}, "key": {"item": "b"}, "contributions": {"amount": fraction(1, 4), "count": fraction(1)}},
            ],
            "excluded": [{"record": 3, "reason": "filter"}],
        }
        self.save_config()
        self.expected.write_text(json.dumps(self.oracle), encoding="utf-8")

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def run_tool(self, output=None):
        return subprocess.run([sys.executable, "-I", "-B", str(self.package / "summarize_csv.py"),
                               "--input", str(self.source), "--config", str(self.config_path),
                               "--output", str(output or self.output)], cwd=self.root,
                              capture_output=True, text=True, timeout=15)

    def run_check(self, checker=None, expected=None, environment=None):
        env = {key: value for key, value in os.environ.items() if not key.startswith("FOUNDRY_")}
        env.update(environment or {})
        return subprocess.run([sys.executable, "-I", "-B", str(checker or self.package / "check_summary.py"),
                               "--input", str(self.source), "--config", str(self.config_path),
                               "--actual", str(self.output), "--expected", str(expected or self.expected),
                               "--report", str(self.report)], cwd=self.root, env=env,
                              capture_output=True, text=True, timeout=15)

    def actual(self):
        completed = self.run_tool()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(self.output.read_text())

    def test_delivered_tool_runs_without_foundry_and_preserves_package_and_inputs(self):
        before = {p: p.read_bytes() for p in self.package.rglob("*") if p.is_file()}
        source_before, config_before = self.source.read_bytes(), self.config_path.read_bytes()
        actual = self.actual()
        self.assertEqual(actual["input_sha256"], hashlib.sha256(source_before).hexdigest())
        self.assertEqual(actual["config_sha256"], hashlib.sha256(config_before).hexdigest())
        self.assertEqual({key: actual[key] for key in self.oracle}, self.oracle)
        self.assertEqual({p: p.read_bytes() for p in self.package.rglob("*") if p.is_file()}, before)
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(self.config_path.read_bytes(), config_before)
        completed = self.run_check()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(self.report.read_text())["status"], "CHECKS_PASS")

    def test_second_new_input_changes_columns_units_groups_and_denominator(self):
        self.source.write_text("sku,batch,mass,u,pieces\nx,green,250,g,2\ny,green,0.75,kg,3\nz,blue,2000,g,4\n")
        self.config.update(group_by=["batch"], filters=[], rows={"key": ["sku"], "duplicates": "error", "missing": "error"}, metrics=[
            {"id": "mass", "op": "sum", "column": "mass", "unit_column": "u", "unit_factors": {"g": "0.001", "kg": "1"}, "unit": "kg", "scale": 3, "rounding": "HALF_EVEN"},
            {"id": "pieces", "op": "sum", "column": "pieces", "unit": "pieces", "scale": 0, "rounding": "DOWN"},
            {"id": "per_piece", "op": "ratio", "numerator": "mass", "denominator": "pieces", "zero_denominator": "error", "unit": "kg/piece", "scale": 2, "rounding": "HALF_UP"},
        ])
        self.save_config()
        actual = self.actual()
        self.assertEqual(actual["groups"], [
            {"key": {"batch": "green"}, "metrics": {"mass": value("1.000", 1, 1, "kg"), "pieces": value("5", 5, 1, "pieces"), "per_piece": value("0.20", 1, 5, "kg/piece")}},
            {"key": {"batch": "blue"}, "metrics": {"mass": value("2.000", 2, 1, "kg"), "pieces": value("4", 4, 1, "pieces"), "per_piece": value("0.50", 1, 2, "kg/piece")}},
        ])
        self.assertEqual(actual["rows"][0]["contributions"], {"mass": fraction(1, 4), "pieces": fraction(2)})
        # A second, independently authored full oracle, with different columns,
        # units and a sum denominator instead of a record count.
        second_oracle = {
            "schema_version": "1.0", "summary": {"input_rows": 3, "included_rows": 3, "excluded_rows": 0},
            "groups": [
                {"key": {"batch": "green"}, "metrics": {"mass": value("1.000", 1, 1, "kg"), "pieces": value("5", 5, 1, "pieces"), "per_piece": value("0.20", 1, 5, "kg/piece")}},
                {"key": {"batch": "blue"}, "metrics": {"mass": value("2.000", 2, 1, "kg"), "pieces": value("4", 4, 1, "pieces"), "per_piece": value("0.50", 1, 2, "kg/piece")}},
            ],
            "rows": [
                {"record": 1, "group": {"batch": "green"}, "key": {"sku": "x"}, "contributions": {"mass": fraction(1, 4), "pieces": fraction(2)}},
                {"record": 2, "group": {"batch": "green"}, "key": {"sku": "y"}, "contributions": {"mass": fraction(3, 4), "pieces": fraction(3)}},
                {"record": 3, "group": {"batch": "blue"}, "key": {"sku": "z"}, "contributions": {"mass": fraction(2), "pieces": fraction(4)}},
            ],
            "excluded": [],
        }
        self.expected.write_text(json.dumps(second_oracle))
        completed = self.run_check()
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_zero_denominator_must_follow_explicit_policy(self):
        self.source.write_text("item,team,amount,unit,stage\na,north,0,yuan,yes\n")
        self.config["metrics"][2].update(numerator="count", denominator="amount")
        self.save_config()
        completed = self.run_tool()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("zero denominator", completed.stderr)
        self.assertFalse(self.output.exists())
        self.config["metrics"][2]["zero_denominator"] = "null"
        self.save_config()
        self.assertEqual(self.actual()["groups"][0]["metrics"]["average"], {"value": None, "exact": None, "unit": "yuan/item"})

    def test_missing_policy_and_required_columns_are_not_silently_guessed(self):
        self.source.write_text("item,team,amount,unit,stage\na,north,,yuan,yes\nb,north,1,yuan,yes\n")
        failed = self.run_tool()
        self.assertIn("missing values", failed.stderr)
        self.assertFalse(self.output.exists())
        self.config["rows"]["missing"] = "skip"
        self.save_config()
        actual = self.actual()
        self.assertEqual(actual["excluded"], [{"record": 1, "reason": "missing", "columns": ["amount"]}])
        self.assertEqual(actual["groups"][0]["metrics"]["amount"], value("1.00", 1, 1, "yuan"))
        self.source.write_text("item,team,unit,stage\na,north,yuan,yes\n")
        missing_column = self.run_tool(self.root / "other.json")
        self.assertIn("missing declared columns", missing_column.stderr)

    def test_all_four_duplicate_policies_are_project_choices(self):
        self.source.write_text("item,team,amount,unit,stage\na,north,1,yuan,yes\na,north,2,yuan,yes\n")
        self.assertIn("duplicate key", self.run_tool().stderr)
        self.assertFalse(self.output.exists())
        for policy, total, records in (("keep_first", "1.00", [1]), ("keep_last", "2.00", [2]), ("all", "3.00", [1, 2])):
            with self.subTest(policy=policy):
                self.config["rows"]["duplicates"] = policy
                self.save_config()
                output = self.root / (policy + ".json")
                completed = self.run_tool(output)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                actual = json.loads(output.read_text())
                self.assertEqual(actual["groups"][0]["metrics"]["amount"]["value"], total)
                self.assertEqual([row["record"] for row in actual["rows"]], records)
                self.assertEqual(actual["summary"]["included_rows"] + actual["summary"]["excluded_rows"], 2)

    def test_decimal_precision_rounding_negative_values_and_large_integers(self):
        for number, rounding, display, numerator, denominator in (
            ("1.005", "HALF_UP", "1.01", 201, 200),
            ("1.005", "HALF_EVEN", "1.00", 201, 200),
            ("-1.005", "HALF_UP", "-1.01", -201, 200),
            ("-1.009", "DOWN", "-1.00", -1009, 1000),
            ("-0.001", "DOWN", "0.00", -1, 1000),
            ("123456789012345678901234567890.01", "HALF_EVEN", "123456789012345678901234567890.01", 12345678901234567890123456789001, 100),
        ):
            with self.subTest(number=number, rounding=rounding):
                self.source.write_text("item,team,amount,unit,stage\na,north," + number + ",yuan,yes\n")
                self.config["metrics"] = [self.config["metrics"][0]]
                self.config["metrics"][0]["rounding"] = rounding
                self.save_config()
                output = self.root / (str(numerator) + rounding + ".json")
                completed = self.run_tool(output)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(output.read_text())["groups"][0]["metrics"]["amount"], value(display, numerator, denominator, "yuan"))

    def test_undeclared_units_invalid_numbers_and_csv_shape_fail_even_with_skip(self):
        self.config["rows"]["missing"] = "skip"
        self.save_config()
        for body in ("a,north,1,dollar,yes\n", "a,north,NaN,yuan,yes\n", "a,north,Infinity,yuan,yes\n", "a,north,1,yuan,yes,extra\n", "a,north,1,yuan\n"):
            with self.subTest(body=body):
                self.source.write_text("item,team,amount,unit,stage\n" + body)
                completed = self.run_tool()
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_configuration_requires_business_policies_and_known_denominator(self):
        variations = []
        missing = deepcopy(self.config)
        del missing["rows"]["duplicates"]
        variations.append(missing)
        unknown = deepcopy(self.config)
        unknown["metrics"][2]["denominator"] = "unspecified-total"
        variations.append(unknown)
        ratio = deepcopy(self.config)
        ratio["metrics"][2]["denominator"] = "average"
        variations.append(ratio)
        float_factor = deepcopy(self.config)
        float_factor["metrics"][0]["unit_factors"]["fen"] = 0.01
        variations.append(float_factor)
        for config in variations:
            with self.subTest(config=config):
                self.config_path.write_text(json.dumps(config))
                self.assertNotEqual(self.run_tool().returncode, 0)
                self.assertFalse(self.output.exists())

    def test_wrong_but_valid_denominator_fails_independent_expectation(self):
        self.config["metrics"][2]["denominator"] = "amount"
        self.save_config()
        self.actual()  # Valid computation; the project selected the wrong business denominator.
        self.assertEqual(self.run_check().returncode, 1)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["failure_kind"], "ASSERTION")

    def test_checker_detects_extra_missing_duplicate_and_changed_row_evidence(self):
        original = self.actual()
        variants = []
        extra = deepcopy(original)
        extra["unsupported-conclusion"] = "accepted"
        variants.append(extra)
        missing = deepcopy(original)
        missing["rows"].pop()
        variants.append(missing)
        duplicate = deepcopy(original)
        duplicate["rows"].append(deepcopy(duplicate["rows"][0]))
        variants.append(duplicate)
        changed = deepcopy(original)
        changed["rows"][0]["contributions"]["amount"] = fraction(11, 100)
        variants.append(changed)
        for index, variant in enumerate(variants):
            self.output.write_text(json.dumps(variant))
            self.report = self.root / ("check-" + str(index) + ".json")
            self.assertEqual(self.run_check().returncode, 1)
            self.assertEqual(json.loads(self.report.read_text())["failure_kind"], "ASSERTION")

    def test_checker_binds_new_input_and_does_not_reexecute_producer(self):
        self.actual()
        (self.package / "summarize_csv.py").write_text("raise RuntimeError('must not execute producer')\n")
        self.assertEqual(self.run_check().returncode, 0)
        self.source.write_text(self.source.read_text() + "d,north,1,yuan,yes\n")
        self.report = self.root / "new-input-check.json"
        self.assertEqual(self.run_check().returncode, 1)
        self.assertIn("not bound", json.loads(self.report.read_text())["diagnostic"])

    def test_checker_uses_protected_copy_and_expected_without_importing_producer(self):
        self.actual()
        verifier = self.root / "verifier"
        checker = verifier / "capabilities/data-summary/check_summary.py"
        checker.parent.mkdir(parents=True)
        shutil.copyfile(self.package / "check_summary.py", checker)
        expected = verifier / "expected.json"
        shutil.copyfile(self.expected, expected)
        env = {"FOUNDRY_VERIFIER_ROOT": str(verifier), "FOUNDRY_CASE_ID": "DATA-CASE", "FOUNDRY_COMMAND_ID": "DATA-COMMAND"}
        completed = self.run_check(checker, expected, env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(self.report.read_text())
        self.assertEqual((report["case_id"], report["command_id"]), ("DATA-CASE", "DATA-COMMAND"))
        self.report = self.root / "unprotected-check.json"
        self.assertEqual(self.run_check(checker, self.expected, env).returncode, 1)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["checks"][0]["status"], "ERROR")
        self.assertNotIn("failure_kind", report)

    def test_malformed_result_is_assertion_but_missing_oracle_is_error(self):
        self.output.write_text("not json")
        self.assertEqual(self.run_check().returncode, 1)
        self.assertEqual(json.loads(self.report.read_text())["failure_kind"], "ASSERTION")
        self.report = self.root / "missing-oracle.json"
        self.expected.unlink()
        self.assertEqual(self.run_check().returncode, 1)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["checks"][0]["status"], "ERROR")
        self.assertNotIn("failure_kind", report)

    def test_empty_input_explicit_zero_policy_and_existing_output_preserved(self):
        self.source.write_text("item,team,amount,unit,stage\n")
        self.config["group_by"] = []
        self.config["metrics"][2]["zero_denominator"] = "null"
        self.save_config()
        actual = self.actual()
        self.assertEqual(actual["summary"], {"input_rows": 0, "included_rows": 0, "excluded_rows": 0})
        self.assertEqual(actual["groups"][0]["metrics"]["amount"], value("0.00", 0, 1, "yuan"))
        self.assertIsNone(actual["groups"][0]["metrics"]["average"]["value"])
        before = self.output.read_bytes()
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertEqual(self.output.read_bytes(), before)

    def test_manifest_keeps_checker_private_and_package_has_no_expected_answer(self):
        manifest = json.loads((self.package / "capability.json").read_text())
        self.assertEqual((manifest["name"], manifest["version"], manifest["usage"]), ("data-summary", "1", "both"))
        self.assertEqual(manifest["verification_files"], ["check_summary.py"])
        self.assertNotIn("check_summary.py", manifest["materials"])
        self.assertNotIn("check_summary.py", [entry["path"] for entry in manifest["tools"]])
        self.assertFalse(list(self.package.glob("*expected*")))
        self.assertNotIn("harness_foundry", (self.package / "summarize_csv.py").read_text())

    def test_actual_cli_reports_use_existing_pass_assertion_and_error_routing(self):
        actual = self.actual()
        binding = {"case_id": "DATA-INTEGRATION", "command_id": "DATA-CHECK-1",
                   "network": {"mode": "NONE"}, "required_checks": ["data-summary"]}
        env = {"FOUNDRY_CASE_ID": binding["case_id"], "FOUNDRY_COMMAND_ID": binding["command_id"]}
        completed = self.run_check(environment=env)
        passed = validate_structured_result(json.loads(self.report.read_text()), binding, completed.returncode)
        self.assertEqual(passed["status"], "PASS")
        self.assertFalse(passed["automatic_retry_allowed"])

        actual["groups"][0]["metrics"]["amount"]["value"] = "0.36"
        self.output.write_text(json.dumps(actual))
        self.report = self.root / "assertion-routing.json"
        completed = self.run_check(environment=env)
        assertion = validate_structured_result(json.loads(self.report.read_text()), binding, completed.returncode)
        self.assertEqual(assertion["status"], "VALIDATION_FAILED")
        self.assertEqual(assertion["failure_domain"], "BUSINESS_ASSERTION")
        self.assertTrue(assertion["automatic_retry_allowed"])

        self.expected.unlink()
        self.report = self.root / "error-routing.json"
        completed = self.run_check(environment=env)
        error = validate_structured_result(json.loads(self.report.read_text()), binding, completed.returncode)
        self.assertEqual(error["status"], "VALIDATION_FAILED")
        self.assertEqual(error["failure_domain"], "VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED")
        self.assertFalse(error["automatic_retry_allowed"])
        self.assertFalse(list(self.root.rglob("*.sqlite3")))


if __name__ == "__main__":
    unittest.main()
