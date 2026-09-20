"""Generic plan behavior through both the Python and public CLI boundaries."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_plan import compile_build_plan, validate_compiled_build_plan
from harness_foundry_factory.models import RequestValidationError


ROOT = Path(__file__).resolve().parents[1]


def request_fixture():
    """Public synthetic requirements, not a historical Candidate or source copy."""
    return {
        "requirement_ir": {
            "program_id": "PROPOSED-DATA-TOOLS", "revision": 1,
            "target": {"id": "DATA-TOOLS", "mission": "Build a local data checking Coding Harness.",
                       "scope": ["Read rows and produce a reproducible summary"], "non_goals": ["Hosted service"]},
            "sources": [{"source_id": "PROJECT-BRIEF", "path_or_uri": "project://brief.md", "loaded_completely": True}],
            "atoms": [
                {"atom_id": "REQ-READ", "text_or_lossless_paraphrase": "Read all input rows.",
                 "source_id": "PROJECT-BRIEF", "source_locator": "#read"},
                {"atom_id": "REQ-REPORT", "text_or_lossless_paraphrase": "Count invalid rows in the output.",
                 "source_id": "PROJECT-BRIEF", "source_locator": "#report"},
            ],
            "acceptance_cases": [
                {"case_id": "READ-ROWS", "atom_ids": ["REQ-READ"], "description": "All three supplied rows are read."},
                {"case_id": "REPORT-COUNT", "atom_ids": ["REQ-REPORT"], "description": "The two invalid rows are reported."},
            ],
            "negative_cases": [{"case_id": "REJECT-MALFORMED", "atom_ids": ["REQ-READ"],
                                "description": "Malformed input is rejected with a diagnostic."}],
        },
        "plan": {
            "schema_version": "1.0", "plan_id": "INITIAL-PLAN", "revision": 1, "requirement_revision": 1,
            "workpacks": [
                {"workpack_id": "IMPLEMENT-READER", "job_id": "READER", "executor": "CODEX",
                 "goal": "Implement the reader and its tests.", "depends_on": [], "atom_ids": ["REQ-READ"],
                 "inputs": [{"kind": "SOURCE", "id": "PROJECT-BRIEF"}],
                 "artifacts": [{"artifact_id": "READER-SOURCE", "path": "src/reader.py"}],
                 "verification": [
                     {"case_id": "READ-ROWS", "argv": ["python3", "-m", "unittest", "tests.test_reader"],
                      "artifact_ids": ["READER-SOURCE"]},
                     {"case_id": "REJECT-MALFORMED", "argv": ["python3", "-m", "unittest", "tests.test_malformed"],
                      "artifact_ids": ["READER-SOURCE"]},
                 ]},
                {"workpack_id": "MAKE-REPORT", "job_id": "REPORT", "executor": "LOCAL",
                 "goal": "Produce the summary using the accepted reader.", "depends_on": ["IMPLEMENT-READER"],
                 "atom_ids": ["REQ-REPORT"], "inputs": [{"kind": "ARTIFACT", "id": "READER-SOURCE"}],
                 "artifacts": [{"artifact_id": "SUMMARY", "path": "outputs/summary.json"}],
                 "verification": [{"case_id": "REPORT-COUNT", "argv": ["python3", "tests/check_summary.py"],
                                   "artifact_ids": ["SUMMARY"]}]},
            ],
        },
    }


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.request = request_fixture()
        self.ir = self.request["requirement_ir"]
        self.plan = self.request["plan"]

    def compile(self):
        return compile_build_plan(self.ir, self.plan)

    def assert_rejected(self, code):
        with self.assertRaises(RequestValidationError) as caught:
            self.compile()
        self.assertEqual(caught.exception.details["reason_code"], code)

    def test_domain_neutral_output_has_exact_declared_tasks_and_no_authority_or_hashes(self):
        original = deepcopy(self.request)
        result = self.compile()
        validate_compiled_build_plan(self.ir, self.plan, result)
        self.assertEqual(result["plan"], self.plan)
        self.assertEqual(result["requirement_coverage"], {"REQ-READ": ["IMPLEMENT-READER"], "REQ-REPORT": ["MAKE-REPORT"]})
        self.assertEqual(result["artifact_index"], {
            "READER-SOURCE": {"workpack_id": "IMPLEMENT-READER", "job_id": "READER", "path": "src/reader.py"},
            "SUMMARY": {"workpack_id": "MAKE-REPORT", "job_id": "REPORT", "path": "outputs/summary.json"},
        })
        self.assertEqual(result["status"], "PLAN_COMPILED_NOT_AUTHORIZED")
        for key in ("authority_validated", "behavior_verified", "execution_started", "writes_performed"):
            self.assertIs(result[key], False)
        for token in ("sha256", "PUBLIC_SKILL", "TTS", "MEDIA_ACCEPTANCE", "LAB-", "LINK-", "MB-P", "epoch"):
            self.assertNotIn(token, json.dumps(result))
        self.assertEqual(self.request, original)
        result["plan"]["workpacks"][0]["goal"] = "Mutated caller output"
        self.assertEqual(self.request, original)

    def test_plan_revision_does_not_require_requirement_refreeze(self):
        before = self.compile()
        self.plan["revision"] = 2
        self.plan["workpacks"][0]["goal"] = "Use a different internal module design."
        after = self.compile()
        self.assertEqual(before["requirement_binding"], after["requirement_binding"])
        self.assertEqual(after["plan"]["revision"], 2)

    def test_local_command_is_optional_static_data_not_implicit_execution(self):
        task = self.plan["workpacks"][1]
        task["local_argv"] = ["python", "-c", "print('declared only')"]
        with patch("subprocess.Popen", side_effect=AssertionError("must not execute")):
            self.assertEqual(self.compile()["plan"]["workpacks"][1]["local_argv"], task["local_argv"])
        for invalid in ([], "python", ["python", "\x00"], ["python", 1]):
            task["local_argv"] = invalid
            self.assert_rejected("BUILD_PLAN_LOCAL_COMMAND_INVALID")
        task["local_argv"] = ["python"]
        task["executor"] = "CODEX"
        self.assert_rejected("BUILD_PLAN_LOCAL_COMMAND_INVALID")

    def test_ids_and_number_of_tasks_are_not_project_specific(self):
        self.plan["workpacks"][0]["workpack_id"] = "PARSE-DOCUMENTS"
        self.plan["workpacks"][1]["depends_on"] = ["PARSE-DOCUMENTS"]
        self.ir["target"]["id"] = "DOCUMENT-INDEX"
        result = self.compile()
        self.assertEqual(result["artifact_index"]["READER-SOURCE"]["workpack_id"], "PARSE-DOCUMENTS")
        self.assertEqual(len(result["plan"]["workpacks"]), 2)

    def test_uncovered_requirement_and_declared_case_cannot_disappear(self):
        self.ir["atoms"].append({**self.ir["atoms"][0], "atom_id": "REQ-EXTRA"})
        self.assert_rejected("BUILD_PLAN_REQUIREMENT_UNCOVERED")
        self.ir["atoms"].pop()
        self.plan["workpacks"][0]["verification"].pop()
        self.assert_rejected("BUILD_PLAN_CASE_UNCOVERED")

    def test_no_artifact_or_requirement_is_accepted_without_a_check(self):
        first = self.plan["workpacks"][0]
        first["artifacts"].append({"artifact_id": "UNTESTED", "path": "untested.py"})
        self.assert_rejected("BUILD_PLAN_ARTIFACT_UNVERIFIED")
        first["artifacts"].pop()
        first["atom_ids"].append("REQ-REPORT")
        self.assert_rejected("BUILD_PLAN_REQUIREMENT_UNVERIFIED")

    def test_wrong_job_or_workpack_cannot_claim_another_output(self):
        self.plan["workpacks"][1]["verification"][0]["artifact_ids"] = ["READER-SOURCE"]
        self.assert_rejected("BUILD_PLAN_CASE_OWNER_MISMATCH")

    def test_artifact_owner_and_overlapping_paths_are_unique(self):
        second = self.plan["workpacks"][1]
        second["artifacts"][0]["artifact_id"] = "READER-SOURCE"
        self.assert_rejected("BUILD_PLAN_ARTIFACT_OWNER_CONFLICT")
        second["artifacts"][0]["artifact_id"] = "SUMMARY"
        for path in ("src/reader.py", "src", "src/reader.py/child"):
            with self.subTest(path=path):
                second["artifacts"][0]["path"] = path
                self.assert_rejected("BUILD_PLAN_ARTIFACT_PATH_CONFLICT")

    def test_artifact_paths_cannot_escape_or_claim_controller_state(self):
        for path in ("/tmp/result", "../result", "a/../result", "a//result", "./result", ".",
                     "a\\result", "C:result", "a\x00result", ".git/index", ".harness-foundry/control.sqlite3"):
            with self.subTest(path=path):
                self.plan["workpacks"][0]["artifacts"][0]["path"] = path
                self.assert_rejected("BUILD_PLAN_ARTIFACT_PATH_INVALID")

    def add_reader_revision(self, name="READER-V2", previous="READER-SOURCE", dependencies=None):
        task = deepcopy(self.plan["workpacks"][0])
        task.update(workpack_id=name, job_id="MAINTENANCE", depends_on=dependencies or ["MAKE-REPORT"],
                    inputs=[{"kind": "ARTIFACT", "id": previous}],
                    artifacts=[{"artifact_id": name, "path": "src/reader.py", "replaces_artifact_id": previous}])
        for check in task["verification"]:
            check["artifact_ids"] = [name]
        self.plan["workpacks"].append(task)
        return task

    def test_sequential_source_edits_preserve_logical_version_ownership(self):
        self.add_reader_revision()
        self.add_reader_revision("READER-V3", "READER-V2", ["READER-V2"])
        self.plan["workpacks"].reverse()  # Not dependent on declaration order.
        result = self.compile()
        validate_compiled_build_plan(self.ir, self.plan, result)
        self.assertEqual(result["artifact_index"]["READER-V3"], {
            "workpack_id": "READER-V3", "job_id": "MAINTENANCE", "path": "src/reader.py",
            "replaces_artifact_id": "READER-V2"})
        result["artifact_index"]["READER-V3"]["replaces_artifact_id"] = "READER-SOURCE"
        with patch("harness_foundry_factory.build_plan.compile_build_plan", side_effect=AssertionError), \
                self.assertRaises(RequestValidationError):
            validate_compiled_build_plan(self.ir, self.plan, result)

    def test_replacement_needs_exact_path_input_and_predecessor(self):
        task = self.add_reader_revision()
        task["artifacts"][0]["replaces_artifact_id"] = "ABSENT"
        self.assert_rejected("BUILD_PLAN_REPLACEMENT_INVALID")
        task["artifacts"][0]["replaces_artifact_id"] = "SUMMARY"
        self.assert_rejected("BUILD_PLAN_REPLACEMENT_INVALID")
        task["artifacts"][0]["replaces_artifact_id"] = "READER-SOURCE"
        task["inputs"] = []
        self.assert_rejected("BUILD_PLAN_REPLACEMENT_INPUT_MISSING")
        task["depends_on"] = []
        self.assert_rejected("BUILD_PLAN_REPLACEMENT_INPUT_MISSING")
        task["artifacts"][0]["replaces_artifact_id"] = "READER-V2"
        self.assert_rejected("BUILD_PLAN_REPLACEMENT_INPUT_MISSING")

    def test_file_replacement_cannot_race_old_version_reader(self):
        task = self.add_reader_revision(dependencies=["IMPLEMENT-READER"])
        self.assert_rejected("BUILD_PLAN_ARTIFACT_READ_ORDER_INVALID")
        # Ordering the report after replacement still reads the wrong version.
        self.plan["workpacks"][1]["depends_on"] = ["READER-V2"]
        self.assert_rejected("BUILD_PLAN_ARTIFACT_READ_ORDER_INVALID")
        self.plan["workpacks"][1]["inputs"][0]["id"] = "READER-V2"
        self.compile()
        self.assertEqual(task["artifacts"][0]["path"], "src/reader.py")

    def test_parallel_replacements_and_skipping_latest_version_fail(self):
        self.add_reader_revision()
        task = self.add_reader_revision("READER-V3")
        self.assert_rejected("BUILD_PLAN_ARTIFACT_PATH_CONFLICT")
        task["depends_on"] = ["READER-V2"]
        self.assert_rejected("BUILD_PLAN_ARTIFACT_PATH_CONFLICT")
        task["artifacts"][0]["replaces_artifact_id"] = "READER-V2"
        task["inputs"][0]["id"] = "READER-V2"
        self.compile()

    def test_unresolved_inputs_cycles_and_missing_dependencies_fail(self):
        second = self.plan["workpacks"][1]
        second["inputs"][0]["id"] = "ABSENT"
        self.assert_rejected("BUILD_PLAN_REFERENCE_UNKNOWN")
        second["inputs"][0]["id"] = "READER-SOURCE"
        second["depends_on"] = []
        self.assert_rejected("BUILD_PLAN_INPUT_DEPENDENCY_MISSING")
        second["depends_on"] = ["IMPLEMENT-READER"]
        self.plan["workpacks"][0]["depends_on"] = ["MAKE-REPORT"]
        self.assert_rejected("BUILD_PLAN_DEPENDENCY_CYCLE")

    def test_transitive_artifact_inputs_and_parallel_tasks_are_supported(self):
        middle = deepcopy(self.plan["workpacks"][1])
        middle.update(workpack_id="CHECK-READER", job_id="CHECK", artifacts=[{"artifact_id": "CHECK", "path": "check.json"}])
        middle["verification"][0]["artifact_ids"] = ["CHECK"]
        self.plan["workpacks"].append(middle)
        self.compile()  # Siblings sharing an already declared predecessor.
        self.plan["workpacks"][1]["depends_on"] = ["CHECK-READER"]
        self.compile()  # Reader is now a transitive predecessor, independent of list order.

    def test_unknown_fields_and_wrong_types_are_not_silently_ignored(self):
        self.plan["execution_authorized"] = True
        self.assert_rejected("BUILD_PLAN_FIELDS_INVALID")
        del self.plan["execution_authorized"]
        self.plan["workpacks"][0]["verification"][0]["argv"] = "echo PASS"
        self.assert_rejected("BUILD_PLAN_VERIFICATION_MISSING")

    def test_stale_and_boolean_revisions_are_rejected(self):
        for revision in (2, True, "1"):
            with self.subTest(revision=revision):
                self.plan["requirement_revision"] = revision
                self.assert_rejected("BUILD_PLAN_REQUIREMENT_REVISION_MISMATCH")

    def test_malformed_boundary_values_return_validation_errors(self):
        for field, invalid in (("source_id", []), ("source_locator", None)):
            original = self.ir["atoms"][0][field]
            self.ir["atoms"][0][field] = invalid
            with self.subTest(field=field), self.assertRaises(RequestValidationError):
                self.compile()
            self.ir["atoms"][0][field] = original
        for invalid in (None, [], "plan"):
            with self.subTest(plan=invalid), self.assertRaises(RequestValidationError):
                compile_build_plan(self.ir, invalid)

    def test_incomplete_source_and_blocking_questions_stop_compilation(self):
        self.ir["sources"][0]["loaded_completely"] = False
        self.assert_rejected("BUILD_PLAN_SOURCE_INCOMPLETE")
        self.ir["sources"][0]["loaded_completely"] = True
        self.ir["open_questions"] = [{"question_id": "PURPOSE", "status": "OPEN"}]
        self.assert_rejected("BUILD_PLAN_REQUIREMENT_UNRESOLVED")
        self.ir["open_questions"][0]["blocking"] = False
        self.compile()

    def test_validator_rejects_producer_corruption_without_calling_producer(self):
        original = self.compile()
        mutations = [
            lambda value: value.update(execution_started=True),
            lambda value: value["plan"]["workpacks"].pop(),
            lambda value: value["artifact_index"].pop("SUMMARY"),
            lambda value: value["artifact_index"]["SUMMARY"].update(job_id="READER"),
            lambda value: value["artifact_index"]["SUMMARY"].update(path="wrong.json"),
            lambda value: value["requirement_coverage"]["REQ-READ"].append("MAKE-REPORT"),
            lambda value: value["requirement_binding"].update(revision=2),
            lambda value: value["requirement_binding"].update(revision=True),
            lambda value: value["plan"].update(revision=True),
            lambda value: value["plan"].update(revision=1.0),
        ]
        with patch("harness_foundry_factory.build_plan.compile_build_plan", side_effect=AssertionError("producer must not be used")):
            validate_compiled_build_plan(self.ir, self.plan, original)
            for mutate in mutations:
                changed = deepcopy(original)
                mutate(changed)
                with self.subTest(output=changed), self.assertRaises(RequestValidationError):
                    validate_compiled_build_plan(self.ir, self.plan, changed)

    def test_cli_compiles_without_creating_state_or_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(json.dumps(self.request))
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/hffactory.py"),
                                     "compile-build-plan", "--request", str(request), "--json"],
                                    cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            body = json.loads(result.stdout)
            self.assertEqual(body, self.compile())
            self.assertEqual(before, {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()})
            self.assertEqual(list(root.iterdir()), [request])
            self.plan["workpacks"][1]["depends_on"] = []
            request.write_text(json.dumps(self.request))
            failed = subprocess.run(result.args, cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                    capture_output=True, text=True, check=False)
            self.assertEqual(failed.returncode, 2, failed.stdout)
            self.assertEqual(json.loads(failed.stdout)["error"]["details"]["reason_code"], "BUILD_PLAN_INPUT_DEPENDENCY_MISSING")

    def test_generic_cli_does_not_import_specialized_authoring_modules(self):
        script = """
import importlib.abc
import sys
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.rsplit('.', 1)[-1] in {'service', 'semantic_contracts', 'traceability',
                'compiler', 'validator', 'generation_readiness', 'lab_runtime'} and fullname.startswith('harness_foundry_factory.'):
            raise AssertionError('generic CLI imported specialized production machinery: ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
from harness_foundry_factory.cli import main
raise SystemExit(main(['compile-build-plan', '--request', '-', '--json']))
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-B", "-c", script], cwd=directory,
                                    env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                                    input=json.dumps(self.request), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), self.compile())
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
