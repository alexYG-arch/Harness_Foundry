"""Root materialization must not absorb downstream behavioral acceptance."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.constants import (
    ROOT_LAYER_BEHAVIORAL_ATOM_POLICY,
    ROOT_LAYER_VALIDATION_SCOPE,
    ROOT_MATERIALIZATION_PRODUCES,
)
from harness_foundry_factory.validator import validate_candidate


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
CREATED_AT = "2026-07-30T00:00:00Z"


class WorkpackLayeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        ir["target"]["output_root"] = str(self.candidate)
        compile_candidate(
            ir,
            SPEC_ROOT,
            self.root / "staging",
            self.candidate,
            CREATED_AT,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _read_json(self, relative: str) -> dict:
        return json.loads(
            (self.candidate / relative).read_text(encoding="utf-8")
        )

    def _write_json(self, relative: str, value: dict) -> None:
        (self.candidate / relative).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    def test_root_layer_is_structural_and_project_workpacks_own_atoms(
        self,
    ) -> None:
        root_index = self._read_json("WORKPACK_INDEX.json")
        root_item = root_index["workpacks"][0]
        root_capsule = self._read_json("CAPSULE.json")
        root_result = self._read_json("WORKPACK_RESULT.json")
        dag = self._read_json("ENGINEERING_PROJECT_DAG.json")
        matrix = self._read_json(
            "canonical_sources/ATOM_COVERAGE_MATRIX.json"
        )

        for document in (root_item, root_capsule, root_result):
            self.assertEqual(document["intent_atom_ids"], [])
            self.assertEqual(
                document["validation_scope"],
                ROOT_LAYER_VALIDATION_SCOPE,
            )
            self.assertEqual(
                document["behavioral_atom_acceptance"],
                ROOT_LAYER_BEHAVIORAL_ATOM_POLICY,
            )
        self.assertEqual(
            root_capsule["required_outputs"],
            list(ROOT_MATERIALIZATION_PRODUCES),
        )

        root_nodes = {
            item["node_id"]: item
            for item in dag["nodes"]
            if item["node_id"]
            in {
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
                "MAIN_EXECUTION_PACKAGE_VALIDATED",
            }
        }
        for node in root_nodes.values():
            self.assertEqual(
                node["validation_scope"], ROOT_LAYER_VALIDATION_SCOPE
            )
            self.assertEqual(
                node["behavioral_atom_acceptance"],
                ROOT_LAYER_BEHAVIORAL_ATOM_POLICY,
            )

        routed_atoms = {
            atom_id
            for directory in (
                "external_lab",
                "linkage_review",
                "main_build",
            )
            for item in self._read_json(
                f"project_start_packages/{directory}/WORKPACK_INDEX.json"
            )["workpacks"]
            for atom_id in item["intent_atom_ids"]
        }
        self.assertEqual(
            routed_atoms,
            {item["atom_id"] for item in matrix["coverage"]},
        )

    def test_root_behavioral_atom_claim_is_rejected(self) -> None:
        capsule = self._read_json("CAPSULE.json")
        capsule["intent_atom_ids"] = ["ATOM-001"]
        self._write_json("CAPSULE.json", capsule)
        workpack_id = self._read_json("WORKPACK_INDEX.json")["workpacks"][0][
            "workpack_id"
        ]
        self._write_json(f"capsules/{workpack_id}.capsule.json", capsule)

        codes = {
            item["code"]
            for item in validate_candidate(self.candidate)[
                "blocking_findings"
            ]
        }

        self.assertIn("ROOT_MATERIALIZATION_CAPABILITY_INVALID", codes)

    def test_root_validation_scope_drift_is_rejected(self) -> None:
        dag = self._read_json("ENGINEERING_PROJECT_DAG.json")
        validation = next(
            item
            for item in dag["nodes"]
            if item["node_id"] == "MAIN_EXECUTION_PACKAGE_VALIDATED"
        )
        validation["validation_scope"] = "FULL_PROGRAM_BEHAVIORAL_ACCEPTANCE"
        self._write_json("ENGINEERING_PROJECT_DAG.json", dag)

        codes = {
            item["code"]
            for item in validate_candidate(self.candidate)[
                "blocking_findings"
            ]
        }

        self.assertIn("ROOT_LAYER_VALIDATION_SCOPE_INVALID", codes)
