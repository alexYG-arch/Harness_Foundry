"""v2.9 explicit production contracts must close label-only Workpacks."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.semantic_contracts import EXPLICIT_PRODUCTION_MODE
from harness_foundry_factory.validator import validate_candidate


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
CREATED_AT = "2026-08-03T00:00:00Z"


def semantic_ir(output_root: Path, execution_root: Path) -> dict:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    value["target"].update(
        {
            "output_root": str(output_root),
            "execution_root": str(execution_root),
            "production_semantics_mode": EXPLICIT_PRODUCTION_MODE,
            "portability_mode": "LOGICAL_RESOURCE_URI",
        }
    )
    value["sources"].append(
        {
            "source_id": "SRC-LOCAL-PORTABILITY",
            "path_or_uri": str(output_root.parent / "authoring-source.md"),
            "snapshot_path": str(output_root.parent / "source-snapshot.md"),
            "sha256": hashlib.sha256(b"local portability source").hexdigest(),
            "authority_level": "HUMAN_APPROVED",
            "scope": "Exercise local source projection and downstream hash repair",
            "loaded_completely": True,
        }
    )
    value["atoms"] = [deepcopy(value["atoms"][0])]
    value["acceptance_cases"] = [deepcopy(value["acceptance_cases"][0])]
    value["negative_cases"] = [deepcopy(value["negative_cases"][0])]
    value["coverage_edges"] = [
        {
            "atom_id": "ATOM-001",
            "workpack_ids": ["MB-P1"],
            "stage_ids": ["P1"],
            "release_step_ids": [],
            "owner_project_ids": ["MAIN_HARNESS_BUILD"],
            "routing_basis": "EXPLICIT_TEST_PRODUCTION_CONTRACT",
        }
    ]
    value["atoms"][0]["production_contract"] = {
        "contract_id": "PROD-ATOM-001",
        "workpack_obligations": [
            {
                "workpack_id": "MB-P1",
                "task_objective": "Produce and lock the runtime/Driver separation design before coding.",
                "required_inputs": [
                    "harness-resource://candidate/canonical_sources/FROZEN_REQUIREMENT_IR.json"
                ],
                "design_questions": [
                    "Which installed entrypoint is distinct from the Build Program Driver?"
                ],
                "deterministic_steps": [
                    "Read the frozen Atom and its routed negative case.",
                    "Write the declared architecture lock using the embedded schema.",
                ],
                "forbidden_inferences": [
                    "Do not invent a substitute entrypoint or omit a required schema field."
                ],
                "completion_rule": "ARCHITECTURE_LOCK_SCHEMA_AND_ORACLE_PASS",
                "artifact_obligations": [
                    {
                        "artifact_id": "ARCHITECTURE_LOCK",
                        "artifact_kind": "LOCK_RECEIPT",
                        "artifact_ref": "harness-resource://execution/project_start_packages/main_build/repository/contracts/architecture_lock.json",
                        "schema": {
                            "type": "object",
                            "required": [
                                "runtime_entrypoint",
                                "driver_entrypoint",
                                "entrypoints_distinct",
                            ],
                            "properties": {
                                "runtime_entrypoint": {"type": "string"},
                                "driver_entrypoint": {"type": "string"},
                                "entrypoints_distinct": {"const": True},
                            },
                        },
                        "production_rule": "Derive both entrypoints from frozen architecture decisions and reject equality.",
                        "validation_rule": {
                            "validator_owner": "MAIN_BUILD_VALIDATOR",
                            "decision_rule": "Schema passes and the two normalized entrypoints differ.",
                            "evidence_required": ["ARCHITECTURE_LOCK_RECEIPT"],
                        },
                        "oracle": {
                            "oracle_id": "ORACLE-ENTRYPOINT-SEPARATION",
                            "independence_level": "INDEPENDENT_IMPLEMENTATION",
                            "decision_rule": "Resolve installed origins without trusting the producer self-report.",
                            "common_mode_exclusions": ["PRODUCER_SELF_REPORT"],
                        },
                        "failure_return": {
                            "error_code": "UNLOCKED_PRODUCTION_TOPOLOGY",
                            "control_node_id": "MAIN_P1_C1",
                            "invalidates": ["P1_BUILD_LOCK_VALID"],
                        },
                    }
                ],
            }
        ],
    }
    return value


class SemanticProductionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.execution = self.root / "execution"
        self.ir = semantic_ir(self.candidate, self.execution)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def compile(self) -> None:
        compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / "staging",
            self.candidate,
            CREATED_AT,
        )

    def finding_codes(self) -> set[str]:
        report = validate_candidate(self.candidate)
        return {
            finding["code"]
            for check in report["checks"]
            for finding in check["findings"]
        }

    def test_compiles_atom_into_task_bundle_and_artifact_obligation(self) -> None:
        self.compile()
        manifest = json.loads(
            (
                self.candidate
                / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        bundle = json.loads(
            (
                self.candidate
                / "project_start_packages/main_build/task_bundles/MB-P1.task_bundle.json"
            ).read_text(encoding="utf-8")
        )
        commands = json.loads(
            (
                self.candidate
                / "project_start_packages/main_build/commands/MB-P1.commands.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["production_semantics_mode"], EXPLICIT_PRODUCTION_MODE)
        self.assertEqual(bundle["required_artifact_ids"], ["ARCHITECTURE_LOCK"])
        self.assertTrue(bundle["semantic_hydration_complete"])
        self.assertFalse(bundle["runtime_binding_complete"])
        self.assertEqual(
            manifest["normative_atom_catalog_sha256"],
            hashlib.sha256(
                (
                    self.candidate
                    / "canonical_sources/NORMATIVE_ATOM_CATALOG.json"
                ).read_bytes()
            ).hexdigest(),
        )
        source_manifest = json.loads(
            (
                self.candidate / "canonical_sources/SOURCE_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        local_source = next(
            item
            for item in source_manifest["sources"]
            if item["source_id"] == "SRC-LOCAL-PORTABILITY"
        )
        self.assertEqual(
            local_source["path_or_uri"],
            "harness-resource://candidate/canonical_sources/evidence/"
            "SRC-LOCAL-PORTABILITY.source_receipt.json",
        )
        self.assertEqual(
            commands["semantic_task_bundle_ref"],
            "task_bundles/MB-P1.task_bundle.json",
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_missing_task_bundle_is_rejected(self) -> None:
        self.compile()
        (
            self.candidate
            / "project_start_packages/main_build/task_bundles/MB-P1.task_bundle.json"
        ).unlink()
        self.assertIn("TASK_BUNDLE_CONTENT_MISMATCH", self.finding_codes())

    def test_semantic_mode_rejects_label_only_atom(self) -> None:
        del self.ir["atoms"][0]["production_contract"]
        with self.assertRaisesRegex(ValueError, "PRODUCTION_CONTRACT_MISSING"):
            self.compile()


if __name__ == "__main__":
    unittest.main()
