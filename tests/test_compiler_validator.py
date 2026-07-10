"""Compiler determinism, output safety, and validator mutation tests."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.validator import validate_candidate


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
CREATED_AT = "2026-07-10T00:00:00Z"


class CompilerValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.ir["target"]["output_root"] = str(self.candidate)
        self.compile_result = self._compile("staging")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _compile(self, staging_name: str, candidate: Path | None = None) -> dict:
        target = candidate or self.candidate
        return compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / staging_name,
            target,
            CREATED_AT,
        )

    def _mutate_json(self, relative_path: str, change) -> None:
        path = self.candidate / relative_path
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _finding_codes(self) -> set[str]:
        report = validate_candidate(self.candidate)
        return {item["code"] for item in report["blocking_findings"]}

    @staticmethod
    def _tree_snapshot(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_complete_fixture_compiles_and_validates(self) -> None:
        report = validate_candidate(self.candidate)

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["valid"])
        self.assertEqual(report["blocking_findings"], [])
        self.assertGreaterEqual(self.compile_result["file_count"], 72)
        self.assertEqual(
            self.compile_result["authoring_terminal_state"],
            "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
        )
        for directory in ("external_lab", "linkage_review", "main_build"):
            self.assertTrue(
                (self.candidate / "project_start_packages" / directory).is_dir()
            )

    def test_rebuild_at_same_path_has_identical_content_hash(self) -> None:
        first_hash = self.compile_result["content_sha256"]
        shutil.rmtree(self.candidate)

        second = self._compile("staging-rebuild")

        self.assertEqual(second["content_sha256"], first_hash)
        self.assertEqual(second["file_count"], self.compile_result["file_count"])
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_same_ir_existing_candidate_is_recovered_without_overwrite(self) -> None:
        provenance_before = (
            self.candidate / "FACTORY_PROVENANCE.json"
        ).read_bytes()

        recovered = self._compile("unused-recovery-staging")

        self.assertTrue(recovered["recovered_existing_candidate"])
        self.assertEqual(
            recovered["content_sha256"], self.compile_result["content_sha256"]
        )
        self.assertFalse((self.root / "unused-recovery-staging").exists())
        self.assertEqual(
            (self.candidate / "FACTORY_PROVENANCE.json").read_bytes(),
            provenance_before,
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_nonempty_output_directory_is_rejected(self) -> None:
        occupied = self.root / "occupied"
        occupied.mkdir()
        (occupied / "user-owned.txt").write_text("preserve", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "candidate root is not empty"):
            self._compile("staging-collision", occupied)

        self.assertEqual(
            (occupied / "user-owned.txt").read_text(encoding="utf-8"), "preserve"
        )

    def test_deleting_p3_from_phase_order_is_rejected(self) -> None:
        self._mutate_json(
            "PHASE_DEPENDENCY_MANIFEST.json",
            lambda value: value.update(
                {"phase_order": [item for item in value["phase_order"] if item != "P3"]}
            ),
        )

        self.assertIn("P3_PHASE_ORDER_INVALID", self._finding_codes())

    def test_reordering_release_steps_is_rejected(self) -> None:
        def swap_first_two(value: dict) -> None:
            value["steps"][0], value["steps"][1] = value["steps"][1], value["steps"][0]

        self._mutate_json("RELEASE_PIPELINE_MANIFEST.json", swap_first_two)

        self.assertIn("RELEASE_PIPELINE_ORDER_INVALID", self._finding_codes())

    def test_granting_execution_authorization_is_rejected(self) -> None:
        self._mutate_json(
            "EXECUTION_AUTHORIZATION.json",
            lambda value: value.update(
                {"status": "GRANTED", "may_auto_advance": True, "max_transitions": 1}
            ),
        )

        self.assertIn("EXECUTION_AUTHORIZATION_PREGRANTED", self._finding_codes())

    def test_removing_codex_false_receipt_negative_case_is_rejected(self) -> None:
        def remove_codex_case(value: dict) -> None:
            value["cases"] = [
                item
                for item in value["cases"]
                if item.get("case_id")
                not in {"NEG-001", "NEG-HF28-CODEX-SELF-REPORT"}
            ]

        self._mutate_json("validation/NEGATIVE_CASES.json", remove_codex_case)

        self.assertIn("FALSE_CODEX_RECEIPT_CASE_MISSING", self._finding_codes())

    def test_forged_self_reported_codex_receipt_authority_is_rejected(self) -> None:
        self._mutate_json(
            "constitution/RUNTIME_ATTESTATION_POLICY.json",
            lambda value: value.update(
                {
                    "self_reported_receipt_is_sufficient": True,
                    "trusted_issuer": "PYTHON_SELF_REPORT",
                    "unverified_invocation_may_complete_stage": True,
                }
            ),
        )

        self.assertEqual(validate_candidate(self.candidate)["status"], "FAIL")

    def test_relative_executable_is_rejected(self) -> None:
        def make_relative(value: dict) -> None:
            value["commands"][0]["executable"] = "python3"
            value["commands"][0]["executable_abs"] = "python3"

        self._mutate_json("COMMAND_MANIFEST.json", make_relative)

        self.assertIn("COMMAND_EXECUTABLE_NOT_ABSOLUTE", self._finding_codes())

    def test_target_id_path_traversal_is_rejected_without_writes(self) -> None:
        before = self._tree_snapshot(self.root)
        traversal_ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        traversal_ir["target"]["id"] = "x/../../../escaped"
        traversal_ir["target"]["output_root"] = str(
            self.root / "traversal-candidate"
        )

        with self.assertRaisesRegex(ValueError, "path-safe identifier"):
            compile_candidate(
                traversal_ir,
                SPEC_ROOT,
                self.root / "traversal-staging",
                self.root / "traversal-candidate",
                CREATED_AT,
            )

        self.assertEqual(self._tree_snapshot(self.root), before)

    def test_manifest_cannot_hide_deleted_start_here(self) -> None:
        self._mutate_json(
            "PACKAGE_MANIFEST.json",
            lambda value: value.update(
                {
                    "required_entry_files": [
                        item
                        for item in value["required_entry_files"]
                        if item != "START_HERE.md"
                    ]
                }
            ),
        )
        (self.candidate / "START_HERE.md").unlink()

        codes = self._finding_codes()
        self.assertIn("REQUIRED_FILE_MANIFEST_TAMPERED", codes)
        self.assertIn("REQUIRED_FILE_MISSING", codes)

    def test_duplicate_atom_id_is_rejected(self) -> None:
        self._mutate_json(
            "canonical_sources/NORMATIVE_ATOM_CATALOG.json",
            lambda value: value["atoms"].append(dict(value["atoms"][0])),
        )

        self.assertIn("ATOM_ID_NOT_UNIQUE", self._finding_codes())

    def test_empty_engineering_dag_edges_are_rejected(self) -> None:
        self._mutate_json(
            "ENGINEERING_PROJECT_DAG.json",
            lambda value: value.update({"edges": []}),
        )

        self.assertIn("ENGINEERING_DAG_EDGES_INVALID", self._finding_codes())

    def test_release_step_with_empty_requires_is_rejected(self) -> None:
        self._mutate_json(
            "RELEASE_PIPELINE_MANIFEST.json",
            lambda value: value["steps"][2].update({"requires": []}),
        )

        self.assertIn("RELEASE_STEP_DEPENDENCY_INVALID", self._finding_codes())

    def test_existing_system_executable_is_rejected_as_planned_target(self) -> None:
        def use_system_executable(value: dict) -> None:
            command = next(
                item
                for item in value["commands"]
                if isinstance(item.get("argv"), list) and item["argv"]
            )
            command["executable"] = "/bin/true"
            command["executable_abs"] = "/bin/true"
            command["argv"][0] = "/bin/true"

        self._mutate_json("COMMAND_MANIFEST.json", use_system_executable)

        self.assertIn("COMMAND_EXECUTABLE_NOT_ABSOLUTE", self._finding_codes())

    def test_empty_three_project_markdown_is_rejected(self) -> None:
        for directory in ("external_lab", "linkage_review", "main_build"):
            for name in ("README.md", "PROJECT_CHARTER.md", "BUILD_INSTALL_PLAN.md"):
                (self.candidate / "project_start_packages" / directory / name).write_text(
                    "", encoding="utf-8"
                )

        self.assertIn("PROJECT_DOCUMENT_CONTRACT_INCOMPLETE", self._finding_codes())

    def test_zero_iteration_loop_policy_is_rejected(self) -> None:
        self._mutate_json(
            "LOOP_POLICY.json",
            lambda value: value["loop_types"]["WORKPACK_REVIEW_FIX"].update(
                {"max_iterations": 0}
            ),
        )

        self.assertIn("LOOP_POLICY_INCOMPLETE", self._finding_codes())

    def test_engineering_node_machine_contract_cannot_be_compressed(self) -> None:
        self._mutate_json(
            "ENGINEERING_PROJECT_DAG.json",
            lambda value: value["nodes"][5].pop("failure_return_node"),
        )

        self.assertIn(
            "ENGINEERING_DAG_NODE_CONTRACT_INCOMPLETE", self._finding_codes()
        )

    def test_every_project_workpack_is_bound_once_and_main_paths_are_explicit(
        self,
    ) -> None:
        dag = json.loads(
            (self.candidate / "ENGINEERING_PROJECT_DAG.json").read_text(
                encoding="utf-8"
            )
        )
        release = json.loads(
            (self.candidate / "RELEASE_PIPELINE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        nodes = {item["node_id"]: item for item in dag["nodes"]}
        registration = nodes["MAIN_PROGRAM_REGISTRATION"]
        self.assertEqual(registration["node_kind"], "CONTROL_REGISTRATION_GATE")
        self.assertEqual(registration["owner_role"], "BUILD_PROGRAM_DRIVER")
        self.assertIsNone(registration["workpack_id"])
        self.assertEqual(
            registration["pipeline_action_id"], "MAIN_PROGRAM_REGISTRATION"
        )
        main_repository = str(
            self.candidate / "project_start_packages/main_build/repository"
        )
        for node_id in (
            "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
            "MAIN_G0_C0",
            "MAIN_P1_C1",
            "MAIN_P2_C2",
            "MAIN_P3_C3_OR_APPROVED_NA",
            "MAIN_P4_LOCAL_CLOSURE",
        ):
            self.assertIn(main_repository, nodes[node_id]["allowed_write_paths"])

        mapped = [
            item["workpack_id"]
            for item in dag["nodes"]
            if item.get("workpack_id")
            and item["node_id"] != "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
        ]
        mapped.extend(
            workpack_id
            for item in dag["nodes"]
            for workpack_id in item.get("project_workpack_sequence", [])
        )
        mapped.extend(
            item["project_workpack_id"]
            for item in release["steps"]
            if item.get("project_workpack_id")
        )
        declared = []
        for directory in ("external_lab", "linkage_review", "main_build"):
            index = json.loads(
                (
                    self.candidate
                    / "project_start_packages"
                    / directory
                    / "WORKPACK_INDEX.json"
                ).read_text(encoding="utf-8")
            )
            declared.extend(item["workpack_id"] for item in index["workpacks"])
        self.assertEqual(sorted(mapped), sorted(declared))
        self.assertEqual(len(mapped), len(set(mapped)))
        self.assertEqual(len(mapped), 16)
        root_index = json.loads(
            (self.candidate / "WORKPACK_INDEX.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            nodes["MAIN_EXECUTION_PACKAGE_MATERIALIZED"]["workpack_id"],
            root_index["workpacks"][0]["workpack_id"],
        )
        self.assertNotIn(root_index["workpacks"][0]["workpack_id"], declared)

    def test_unknown_engineering_workpack_reference_is_rejected(self) -> None:
        def replace_workpack(value: dict) -> None:
            node = next(item for item in value["nodes"] if item.get("workpack_id"))
            node["workpack_id"] = "TOTALLY-NONEXISTENT-WORKPACK"

        self._mutate_json("ENGINEERING_PROJECT_DAG.json", replace_workpack)

        codes = self._finding_codes()
        self.assertIn("ENGINEERING_WORKPACK_BINDING_INVALID", codes)
        self.assertIn("ENGINEERING_WORKPACK_REF_UNRESOLVED", codes)

    def test_project_workpack_sequence_or_release_mapping_cannot_be_dropped(
        self,
    ) -> None:
        def drop_sequence_item(value: dict) -> None:
            node = next(
                item for item in value["nodes"] if item["node_id"] == "LAB_BOOTSTRAP"
            )
            node["project_workpack_sequence"] = node[
                "project_workpack_sequence"
            ][:-1]

        self._mutate_json("ENGINEERING_PROJECT_DAG.json", drop_sequence_item)

        codes = self._finding_codes()
        self.assertIn("ENGINEERING_WORKPACK_BINDING_INVALID", codes)
        self.assertIn("PROJECT_WORKPACK_COVERAGE_INVALID", codes)

    def test_unknown_release_workpack_reference_is_rejected(self) -> None:
        def replace_workpack(value: dict) -> None:
            step = next(
                item
                for item in value["steps"]
                if item.get("project_workpack_id")
            )
            step["project_workpack_id"] = "TOTALLY-NONEXISTENT-WORKPACK"

        self._mutate_json("RELEASE_PIPELINE_MANIFEST.json", replace_workpack)

        codes = self._finding_codes()
        self.assertIn("RELEASE_WORKPACK_BINDING_INVALID", codes)
        self.assertIn("PROJECT_WORKPACK_COVERAGE_INVALID", codes)

    def test_never_produced_project_workpack_requirement_is_rejected(self) -> None:
        self._mutate_json(
            "project_start_packages/external_lab/WORKPACK_INDEX.json",
            lambda value: value["workpacks"][1].update(
                {"requires": ["NEVER_PRODUCED_CAPABILITY"]}
            ),
        )

        self.assertIn(
            "PROJECT_WORKPACK_EXECUTION_CONTRACT_INVALID",
            self._finding_codes(),
        )

    def test_deleting_project_command_surface_is_rejected(self) -> None:
        self._mutate_json(
            "project_start_packages/main_build/COMMAND_MANIFEST.json",
            lambda value: value.update({"commands": []}),
        )

        codes = self._finding_codes()
        self.assertIn("PROJECT_COMMAND_MANIFEST_INVALID", codes)
        self.assertIn("PROJECT_WORKPACK_COMMAND_BINDING_INVALID", codes)

    def test_phase_atom_routes_to_matching_project_workpacks_and_artifacts(
        self,
    ) -> None:
        matrix = json.loads(
            (
                self.candidate
                / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        atom = next(item for item in matrix["coverage"] if item["atom_id"] == "ATOM-002")
        self.assertEqual(atom["workpack_ids"], ["MB-P2", "MB-P3", "MB-P4"])
        self.assertEqual(
            atom["stage_ids"], ["P2", "P3", "C3", "P4_BUILD_INPUT"]
        )
        for workpack_id in ("MB-P3", "MB-P4"):
            index = json.loads(
                (
                    self.candidate
                    / "project_start_packages/main_build/WORKPACK_INDEX.json"
                ).read_text(encoding="utf-8")
            )
            item = next(
                value
                for value in index["workpacks"]
                if value["workpack_id"] == workpack_id
            )
            capsule = json.loads(
                (
                    self.candidate
                    / f"project_start_packages/main_build/capsules/{workpack_id}.capsule.json"
                ).read_text(encoding="utf-8")
            )
            result = json.loads(
                (
                    self.candidate
                    / f"project_start_packages/main_build/results/{workpack_id}.result.json"
                ).read_text(encoding="utf-8")
            )
            self.assertIn("ATOM-002", item["intent_atom_ids"])
            self.assertIn("ATOM-002", capsule["intent_atom_ids"])
            self.assertIn("ATOM-002", result["intent_atom_ids"])

    def test_atom_coverage_cannot_be_redirected_to_wrong_phase(self) -> None:
        self._mutate_json(
            "canonical_sources/ATOM_COVERAGE_MATRIX.json",
            lambda value: next(
                item
                for item in value["coverage"]
                if item["atom_id"] == "ATOM-002"
            ).update(
                {
                    "workpack_ids": ["MB-G0"],
                    "stage_ids": ["G0"],
                    "owner_project_ids": ["MAIN_HARNESS_BUILD"],
                }
            ),
        )

        self.assertIn("COVERAGE_REFERENCE_UNRESOLVED", self._finding_codes())

    def test_project_workpack_atom_reverse_binding_cannot_be_removed(self) -> None:
        def remove_atom(value: dict) -> None:
            item = next(
                row for row in value["workpacks"] if row["workpack_id"] == "MB-P4"
            )
            item["intent_atom_ids"] = []

        self._mutate_json(
            "project_start_packages/main_build/WORKPACK_INDEX.json",
            remove_atom,
        )

        self.assertIn(
            "PROJECT_WORKPACK_EXECUTION_CONTRACT_INVALID",
            self._finding_codes(),
        )

    def test_explicit_frozen_atom_coverage_overrides_semantic_default(self) -> None:
        explicit_candidate = self.root / "explicit-coverage-candidate"
        self.ir["target"]["output_root"] = str(explicit_candidate)
        self.ir["coverage_edges"] = [
            {
                "atom_id": "ATOM-001",
                "workpack_ids": ["MB-P1"],
                "stage_ids": ["P1"],
                "release_step_ids": [],
                "owner_project_ids": ["MAIN_HARNESS_BUILD"],
                "routing_basis": "EXPLICIT_USER_CONFIRMED",
            }
        ]

        compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / "explicit-coverage-staging",
            explicit_candidate,
            CREATED_AT,
        )

        matrix = json.loads(
            (
                explicit_candidate
                / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        atom = next(
            item for item in matrix["coverage"] if item["atom_id"] == "ATOM-001"
        )
        self.assertEqual(atom["workpack_ids"], ["MB-P1"])
        self.assertEqual(atom["stage_ids"], ["P1"])
        self.assertEqual(atom["routing_basis"], "EXPLICIT_USER_CONFIRMED")
        self.assertEqual(validate_candidate(explicit_candidate)["status"], "PASS")

    def test_python_target_still_requires_codex_for_coding_workpacks(self) -> None:
        python_candidate = self.root / "python-runtime-candidate"
        self.ir["target"]["output_root"] = str(python_candidate)
        self.ir["target"]["primary_runtime"] = "Python 3.11"

        compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / "python-runtime-staging",
            python_candidate,
            CREATED_AT,
        )

        ownership = json.loads(
            (
                python_candidate / "constitution/RUNTIME_OWNERSHIP.json"
            ).read_text(encoding="utf-8")
        )
        commands = json.loads(
            (
                python_candidate
                / "project_start_packages/main_build/COMMAND_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        coding = next(
            item
            for item in commands["commands"]
            if item["command_id"] == "MB-CODEX-CODING"
        )
        self.assertEqual(ownership["required_executor"]["name"], "Python 3.11")
        self.assertEqual(ownership["coding_agent_executor"]["name"], "Codex")
        self.assertTrue(coding["executable_abs"].endswith("/codex"))
        self.assertIsNone(coding["argv"])
        self.assertEqual(validate_candidate(python_candidate)["status"], "PASS")

    def test_codex_coding_command_cannot_be_replaced_by_python(self) -> None:
        def replace_executor(value: dict) -> None:
            command = next(
                item
                for item in value["commands"]
                if item["command_id"] == "MB-CODEX-CODING"
            )
            python = str(
                self.candidate
                / "project_start_packages/main_build/.venv/bin/python"
            )
            command["executable"] = python
            command["executable_abs"] = python

        self._mutate_json(
            "project_start_packages/main_build/COMMAND_MANIFEST.json",
            replace_executor,
        )

        self.assertIn("CODEX_CODING_COMMAND_SUBSTITUTED", self._finding_codes())

    def test_release_pipeline_cannot_omit_certification_environment_node(self) -> None:
        def remove_node(value: dict) -> None:
            value["steps"] = [
                item
                for item in value["steps"]
                if item["step_id"] != "SINGLE_CERTIFICATION_ENV_CREATE"
            ]

        self._mutate_json("RELEASE_PIPELINE_MANIFEST.json", remove_node)

        self.assertIn("RELEASE_PIPELINE_ORDER_INVALID", self._finding_codes())

    def test_control_plane_epoch_and_hash_binding_drift_is_rejected(self) -> None:
        self._mutate_json(
            "PROGRAM_AUTOMATION_POLICY.json",
            lambda value: value.update(
                {"control_plane_epoch": 1, "profile_lock_hash": "f" * 64}
            ),
        )

        self.assertIn("CONTROL_ASSET_BINDING_MISMATCH", self._finding_codes())

    def test_empty_invalidation_edges_are_rejected(self) -> None:
        self._mutate_json(
            "INVALIDATION_DAG.json",
            lambda value: value.update({"edges": []}),
        )

        self.assertIn("INVALIDATION_DAG_INCOMPLETE", self._finding_codes())

    def test_tampered_ledger_event_hash_is_rejected(self) -> None:
        path = self.candidate / "PHASE_TRANSITION_LEDGER.jsonl"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["event_hash"] = "0" * 64
        path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")

        self.assertIn("LEDGER_EVENT_HASH_INVALID", self._finding_codes())

    def test_profile_lock_drift_is_rejected(self) -> None:
        self._mutate_json(
            "PROFILE_LOCK.json",
            lambda value: value.update({"selected_profile": "LITE"}),
        )

        codes = self._finding_codes()
        self.assertIn("PROFILE_LOCK_HASH_MISMATCH", codes)
        self.assertIn("PROFILE_LOCK_BOUNDARY_INVALID", codes)

    def test_program_author_role_escalation_is_rejected(self) -> None:
        self._mutate_json(
            "PACKAGE_ROLES.json",
            lambda value: value["roles"]["program_author"].update(
                {"may_execute_workpacks": True}
            ),
        )

        self.assertIn("PROGRAM_AUTHOR_AUTHORITY_ESCALATED", self._finding_codes())

    def test_duplicate_coverage_row_is_rejected(self) -> None:
        self._mutate_json(
            "canonical_sources/ATOM_COVERAGE_MATRIX.json",
            lambda value: value["coverage"].append(dict(value["coverage"][0])),
        )

        self.assertIn("COVERAGE_ATOM_ID_NOT_UNIQUE", self._finding_codes())


if __name__ == "__main__":
    unittest.main()
