"""v2.9 explicit production contracts must close label-only Workpacks."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.invariant_contracts import registered_operator_findings
from harness_foundry_factory.semantic_contracts import (
    build_artifact_obligation_manifest,
    build_composite_dependency_graph,
    compile_declared_production_contracts,
    DETERMINISTIC_DERIVATION_POLICY,
    EXPLICIT_PRODUCTION_MODE,
    negative_case_specs_with_mandatory_controls,
    oracle_evaluator_registry,
    PUBLIC_SKILL_METAMORPHIC_ENTRYPOINT_REF,
    PUBLIC_SKILL_METAMORPHIC_REPOSITORY_URL,
    PUBLIC_SKILL_METAMORPHIC_RESOLUTION_RECEIPT_REF,
    PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT,
    PUBLIC_SKILL_JOB_PIPELINE_ENTRYPOINT,
    RESUMABLE_STAGE_ORDER,
    validate_composite_dependency_graph,
    validate_explicit_production_contracts,
    _schema_declares_json_pointer,
)
from harness_foundry_factory.traceability import normalize_ir_coverage
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


def schema_declares_pointer(schema: dict, pointer: str) -> bool:
    """Resolve a self JSON pointer without using Producer implementation."""

    if not pointer.startswith("/"):
        return True
    current: object = schema
    for token in pointer.removeprefix("/").split("/"):
        if not isinstance(current, dict):
            return False
        if token in {"*", "-1"} or token.isdigit():
            current = current.get("items")
            continue
        properties = current.get("properties")
        if not isinstance(properties, dict) or token not in properties:
            return False
        current = properties[token]
    return isinstance(current, dict)


class SemanticProductionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.execution = self.root / "execution"
        self.ir = semantic_ir(self.candidate, self.execution)

    def tearDown(self) -> None:
        self.make_candidate_writable()
        self.temporary.cleanup()

    def make_candidate_writable(self) -> None:
        if not self.candidate.exists():
            return
        for path in (self.candidate, *self.candidate.rglob("*")):
            if not path.is_symlink():
                mode = path.stat().st_mode
                path.chmod(mode | (0o700 if path.is_dir() else 0o600))

    def compile(self) -> None:
        compile_candidate(
            self.ir,
            SPEC_ROOT,
            self.root / "staging",
            self.candidate,
            CREATED_AT,
        )

    def configure_derived_media_atoms(self, kinds: tuple[str, ...]) -> None:
        self.ir["atoms"] = [
            {
                "atom_id": f"ATOM-DERIVED-{index}",
                "text_or_lossless_paraphrase": f"Produce {kind}.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": kind,
            }
            for index, kind in enumerate(kinds, 1)
        ]
        self.ir["coverage_edges"] = normalize_ir_coverage(self.ir)[
            "coverage_edges"
        ]
        atom_ids = [item["atom_id"] for item in self.ir["atoms"]]
        for case in (
            *self.ir["acceptance_cases"],
            *self.ir["negative_cases"],
        ):
            case["atom_ids"] = list(atom_ids)
        self.ir["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        self.ir["target"]["artifact_schema_catalog"] = {
            item["atom_id"]: {
                "artifact_kind": item["verification_mode"],
                "schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "PASS"}},
                },
            }
            for item in self.ir["atoms"]
        }

    def finding_codes(self) -> set[str]:
        report = validate_candidate(self.candidate)
        return {
            finding["code"]
            for check in report["checks"]
            for finding in check["findings"]
        }

    def test_semantic_repair_shadow_baseline_is_self_consistent(self) -> None:
        path = (
            REPOSITORY_ROOT
            / "tests/fixtures/foundry_semantic_repair_shadow_baseline_v1.json"
        )
        fixture = json.loads(path.read_text(encoding="utf-8"))
        fingerprint = fixture.pop("aggregate_fingerprint")

        self.assertEqual(
            fingerprint,
            hashlib.sha256(
                json.dumps(
                    fixture,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )
        baseline = fixture["baseline_binding"]
        preflight_path = REPOSITORY_ROOT / baseline["preflight_receipt_ref"]
        preflight_text = preflight_path.read_text(encoding="utf-8")
        self.assertIn(baseline["git_head"], preflight_text)
        for artifact in baseline["loaded_implementation"]:
            self.assertIn(artifact["path"], preflight_text)
            self.assertIn(artifact["sha256"], preflight_text)
        self.assertEqual(
            set(fixture["protected_contracts"]),
            {
                "AUTHORING_STOP_REMAINS_NON_EXECUTING",
                "CANDIDATE_PUBLICATION_REMAINS_ATOMIC_AND_IMMUTABLE",
                "NO_EXECUTION_ROOT_OR_AUTHORIZATION_IS_CREATED_BY_REPAIR_TESTS",
                "EXISTING_FAILURE_CODES_REMAIN_STABLE_UNLESS_LISTED_IN_INTENTIONAL_DELTA",
                "PUBLIC_SOURCE_FACTS_REQUIRE_HASH_VERIFIED_RUNTIME_RESOLUTION",
                "CONDITIONAL_INVARIANTS_BIND_EXACT_SCHEMA_DISCRIMINATOR_BRANCHES",
                "CASE_AND_AGGREGATION_SHA256_VALUES_BIND_REFERENCED_BYTES",
                "NEGATIVE_MUTATIONS_REMAIN_MACHINE_APPLICABLE_AND_EVIDENCED",
                "EVERY_INVARIANT_OPERAND_RESOLVES_AND_OPERATOR_SEMANTICS_ARE_COMPLETE",
                "PUBLIC_SOURCE_RESOLVER_IS_REACHABLE_FROM_ITS_OWNED_LAB_COMMAND",
            },
        )
        reproductions = fixture["known_bad_reproductions"]
        self.assertEqual(len(reproductions), 23)
        self.assertEqual(
            len({item["case_id"] for item in reproductions}),
            len(reproductions),
        )
        for reproduction in reproductions:
            method_name = reproduction["regression_test_method"]
            method = getattr(type(self), method_name)
            self.assertIn(
                reproduction["post_repair_failure_code"],
                inspect.getsource(method),
            )
        self.assertEqual(
            fixture["mutation_positions"], ["FIRST", "MIDDLE", "LAST"]
        )

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

    def test_job_artifact_write_root_projects_through_workpack_command_and_dag(
        self,
    ) -> None:
        artifact_ref = (
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/"
            "contracts/architecture_lock.json"
        )
        self.ir["atoms"][0]["production_contract"]["workpack_obligations"][0][
            "artifact_obligations"
        ][0]["artifact_ref"] = artifact_ref

        self.compile()

        artifact_root = (
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/contracts"
        )
        project_root = self.candidate / "project_start_packages/main_build"
        index = json.loads(
            (project_root / "WORKPACK_INDEX.json").read_text(encoding="utf-8")
        )
        workpack = next(
            item for item in index["workpacks"] if item["workpack_id"] == "MB-P1"
        )
        capsule = json.loads(
            (project_root / "capsules/MB-P1.capsule.json").read_text(
                encoding="utf-8"
            )
        )
        command_manifest = json.loads(
            (project_root / "commands/MB-P1.commands.json").read_text(
                encoding="utf-8"
            )
        )
        dag = json.loads(
            (self.candidate / "ENGINEERING_PROJECT_DAG.json").read_text(
                encoding="utf-8"
            )
        )
        node = next(
            item for item in dag["nodes"] if item["node_id"] == "MAIN_P1_C1"
        )
        matrix = json.loads(
            (
                self.candidate
                / "validation/DAG_PATH_CONTAINMENT_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        matrix_row = next(
            item
            for item in matrix["rows"]
            if item["node_id"] == "MAIN_P1_C1"
        )

        self.assertEqual(workpack["required_artifact_refs"], [artifact_ref])
        self.assertIn(artifact_root, workpack["allowed_write_paths"])
        self.assertEqual(capsule["allowed_write_paths"], workpack["allowed_write_paths"])
        self.assertEqual(
            command_manifest["workpack_artifact_write_roots"],
            [artifact_root],
        )
        coding = next(
            command
            for command in command_manifest["commands"]
            if command["command_id"] == "MB-CODEX-CODING"
        )
        test = next(
            command
            for command in command_manifest["commands"]
            if command["command_id"] == "MB-TEST"
        )
        self.assertNotIn(artifact_root, coding["allowed_write_roots"])
        self.assertEqual(
            coding["job_artifact_write_scopes"],
            [
                {
                    "job_id": "JOB-SEMANTIC-001",
                    "allowed_write_roots": [artifact_root],
                }
            ],
        )
        self.assertEqual(coding["artifact_write_scope_mode"], "ONE_JOB_LEASE_REQUIRED")
        self.assertTrue(coding["job_artifact_lease_required"])
        self.assertIsNone(coding["active_job_artifact_lease_ref"])
        self.assertEqual(
            coding["job_artifact_scope_activation_policy"],
            "NO_JOB_ARTIFACT_ROOT_IS_ACTIVE_WITHOUT_EXACTLY_ONE_CURRENT_LEASE",
        )
        lease = coding["job_artifact_lease_contract"]
        self.assertEqual(
            lease["selection_cardinality"],
            "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_INVOCATION",
        )
        self.assertEqual(len(lease["job_scope_bindings"]), 1)
        self.assertEqual(
            lease["receipt_schema"]["oneOf"][0]["properties"]["job_id"],
            {"const": "JOB-SEMANTIC-001"},
        )
        self.assertEqual(
            lease["receipt_schema"]["oneOf"][0]["properties"]
            ["allowed_write_roots"],
            {"const": [artifact_root]},
        )
        self.assertEqual(test["job_artifact_write_scopes"], [])
        self.assertFalse(test["job_artifact_lease_required"])
        self.assertIsNone(test["job_artifact_lease_contract"])
        self.assertNotIn(artifact_root, test["allowed_write_roots"])
        self.assertIn("-B", test["argv"])
        self.assertIn("no:cacheprovider", test["argv"])
        self.assertEqual(test["environment"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
        self.assertTrue(test["argv"][test["argv"].index("--basetemp") + 1].endswith("/MB-P1/pytest-tmp"))
        self.assertIn(artifact_root, node["allowed_write_paths"])
        self.assertEqual(matrix_row["workpack_artifact_refs"], [artifact_ref])
        self.assertEqual(
            matrix_row["contained_workpack_artifact_refs"], [artifact_ref]
        )
        self.assertEqual(matrix_row["outside_workpack_artifact_refs"], [])
        self.assertEqual(matrix_row["status"], "PASS")
        self.assertEqual(
            workpack["job_artifact_write_scopes"],
            coding["job_artifact_write_scopes"],
        )
        self.assertEqual(
            capsule["job_artifact_write_scopes"],
            coding["job_artifact_write_scopes"],
        )
        self.assertEqual(
            workpack["job_artifact_scope_activation_policy"],
            coding["job_artifact_scope_activation_policy"],
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        standalone = subprocess.run(
            [sys.executable, "tools/self_check.py"],
            cwd=self.candidate,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            standalone.returncode,
            0,
            msg=standalone.stdout + standalone.stderr,
        )
        self.assertEqual(json.loads(standalone.stdout)["status"], "PASS")

    def test_validator_rejects_command_that_drops_job_artifact_root(
        self,
    ) -> None:
        artifact_ref = (
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/"
            "contracts/architecture_lock.json"
        )
        artifact_root = artifact_ref.rsplit("/", 1)[0]
        self.ir["atoms"][0]["production_contract"]["workpack_obligations"][0][
            "artifact_obligations"
        ][0]["artifact_ref"] = artifact_ref
        self.compile()
        self.make_candidate_writable()

        command_path = (
            self.candidate
            / "project_start_packages/main_build/commands/MB-P1.commands.json"
        )
        commands = json.loads(command_path.read_text(encoding="utf-8"))
        commands["commands"][0]["job_artifact_write_scopes"][0][
            "allowed_write_roots"
        ].remove(artifact_root)
        command_without_hash = dict(commands["commands"][0])
        command_without_hash.pop("command_sha256", None)
        commands["commands"][0]["command_sha256"] = hashlib.sha256(
            json.dumps(
                command_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest_without_hash = dict(commands)
        manifest_without_hash.pop("manifest_sha256", None)
        commands["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                manifest_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        command_path.write_text(
            json.dumps(commands, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        index_path = (
            self.candidate
            / "project_start_packages/main_build/WORKPACK_INDEX.json"
        )
        index = json.loads(index_path.read_text(encoding="utf-8"))
        workpack = next(
            item for item in index["workpacks"] if item["workpack_id"] == "MB-P1"
        )
        workpack["command_manifest_sha256"] = hashlib.sha256(
            command_path.read_bytes()
        ).hexdigest()
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "PROJECT_WORKPACK_COMMAND_BINDING_INVALID",
            self.finding_codes(),
        )

    def test_three_job_artifact_roots_require_separate_command_leases(
        self,
    ) -> None:
        obligation = self.ir["atoms"][0]["production_contract"][
            "workpack_obligations"
        ][0]
        base = obligation["artifact_obligations"][0]
        obligation["artifact_obligations"] = []
        for index in range(1, 4):
            artifact = deepcopy(base)
            artifact["artifact_id"] = f"ARCHITECTURE_LOCK_{index}"
            artifact["artifact_ref"] = (
                "harness-resource://execution/jobs/"
                f"JOB-SEMANTIC-{index:03d}/contracts/architecture_lock.json"
            )
            obligation["artifact_obligations"].append(artifact)

        self.compile()

        commands = json.loads(
            (
                self.candidate
                / "project_start_packages/main_build/commands/MB-P1.commands.json"
            ).read_text(encoding="utf-8")
        )["commands"]
        coding = next(
            command
            for command in commands
            if command["command_id"] == "MB-CODEX-CODING"
        )
        test = next(
            command for command in commands if command["command_id"] == "MB-TEST"
        )
        scopes = coding["job_artifact_write_scopes"]
        self.assertEqual(
            [scope["job_id"] for scope in scopes],
            [
                "JOB-SEMANTIC-001",
                "JOB-SEMANTIC-002",
                "JOB-SEMANTIC-003",
            ],
        )
        self.assertTrue(
            all(
                len(scope["allowed_write_roots"]) == 1
                and f"/jobs/{scope['job_id']}/"
                in scope["allowed_write_roots"][0]
                for scope in scopes
            )
        )
        self.assertFalse(
            any("/jobs/" in root for root in coding["allowed_write_roots"])
        )
        lease = coding["job_artifact_lease_contract"]
        self.assertTrue(coding["job_artifact_lease_required"])
        self.assertEqual(
            [item["job_id"] for item in lease["job_scope_bindings"]],
            [
                "JOB-SEMANTIC-001",
                "JOB-SEMANTIC-002",
                "JOB-SEMANTIC-003",
            ],
        )
        self.assertEqual(len(lease["receipt_schema"]["oneOf"]), 3)
        for binding, branch in zip(
            lease["job_scope_bindings"],
            lease["receipt_schema"]["oneOf"],
            strict=True,
        ):
            selected = branch["properties"]
            self.assertEqual(selected["job_id"], {"const": binding["job_id"]})
            self.assertEqual(
                selected["allowed_write_roots"],
                {"const": binding["allowed_write_roots"]},
            )
            self.assertEqual(
                selected["scope_sha256"],
                {"const": binding["scope_sha256"]},
            )
        self.assertEqual(test["job_artifact_write_scopes"], [])
        self.assertFalse(
            any("/jobs/" in root for root in test["allowed_write_roots"])
        )

    def test_validator_rejects_job_lease_schema_scope_substitution(
        self,
    ) -> None:
        artifact_ref = (
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/"
            "contracts/architecture_lock.json"
        )
        self.ir["atoms"][0]["production_contract"]["workpack_obligations"][0][
            "artifact_obligations"
        ][0]["artifact_ref"] = artifact_ref
        self.compile()
        self.make_candidate_writable()

        project_root = self.candidate / "project_start_packages/main_build"
        command_path = project_root / "commands/MB-P1.commands.json"
        command_manifest = json.loads(command_path.read_text(encoding="utf-8"))
        coding = next(
            item
            for item in command_manifest["commands"]
            if item["command_id"] == "MB-CODEX-CODING"
        )
        coding["job_artifact_lease_contract"]["receipt_schema"]["oneOf"][0][
            "properties"
        ]["scope_sha256"]["const"] = "0" * 64
        command_without_hash = dict(coding)
        command_without_hash.pop("command_sha256", None)
        coding["command_sha256"] = hashlib.sha256(
            json.dumps(
                command_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest_without_hash = dict(command_manifest)
        manifest_without_hash.pop("manifest_sha256", None)
        command_manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                manifest_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        command_path.write_text(
            json.dumps(
                command_manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        index_path = project_root / "WORKPACK_INDEX.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        workpack = next(
            item
            for item in index["workpacks"]
            if item["workpack_id"] == "MB-P1"
        )
        workpack["command_manifest_sha256"] = hashlib.sha256(
            command_path.read_bytes()
        ).hexdigest()
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "PROJECT_WORKPACK_COMMAND_BINDING_INVALID",
            self.finding_codes(),
        )

    def test_artifact_dependencies_reject_future_phase_and_cycle(self) -> None:
        value = deepcopy(self.ir)
        value["coverage_edges"][0]["workpack_ids"] = ["MB-P1", "MB-P2"]
        first = value["atoms"][0]["production_contract"][
            "workpack_obligations"
        ][0]
        second = deepcopy(first)
        second["workpack_id"] = "MB-P2"
        first_artifact = first["artifact_obligations"][0]
        second_artifact = second["artifact_obligations"][0]
        second_artifact["artifact_id"] = "FUTURE_LOCK"
        second_artifact["artifact_ref"] = (
            "harness-resource://execution/artifacts/ATOM-001/MB-P2/future.json"
        )
        first_artifact["depends_on_artifact_ids"] = ["FUTURE_LOCK"]
        second_artifact["depends_on_artifact_ids"] = ["ARCHITECTURE_LOCK"]
        value["atoms"][0]["production_contract"]["workpack_obligations"].append(
            second
        )

        codes = {
            finding["code"]
            for finding in validate_explicit_production_contracts(value)
        }
        self.assertIn("ARTIFACT_DEPENDENCY_FUTURE_PHASE", codes)
        self.assertIn("ARTIFACT_DEPENDENCY_CYCLE", codes)

    def test_composite_dependency_graph_rejects_cross_plane_cycle(self) -> None:
        artifact_index = {
            "ART-MB-P3": {
                "workpack_id": "MB-P3",
                "depends_on_artifact_ids": ["ART-LAB"],
            },
            "ART-MB-P4": {
                "workpack_id": "MB-P4",
                "depends_on_artifact_ids": [],
            },
            "ART-LAB": {
                "workpack_id": "LAB-CERTIFICATION",
                "depends_on_artifact_ids": [],
            },
        }

        with self.assertRaisesRegex(ValueError, "COMPOSITE_DEPENDENCY_CYCLE"):
            build_composite_dependency_graph(artifact_index)

        artifact_index["ART-MB-P3"]["depends_on_artifact_ids"] = []
        artifact_index["ART-MB-P4"]["depends_on_artifact_ids"] = [
            "ART-MB-P3"
        ]
        graph = build_composite_dependency_graph(artifact_index)
        self.assertEqual(
            graph["graph_kind"],
            "ARTIFACT_WORKPACK_ENGINEERING_RELEASE_COMPOSITE",
        )
        self.assertEqual(
            graph["edge_direction"], "PREREQUISITE_TO_CONSUMER"
        )
        self.assertEqual(graph["status"], "ACYCLIC")
        self.assertTrue(
            {
                "ARTIFACT:ART-MB-P3",
                "ARTIFACT:ART-MB-P4",
                "ARTIFACT:ART-LAB",
            }.issubset({item["node_id"] for item in graph["nodes"]})
        )
        node_kinds = {item["node_kind"] for item in graph["nodes"]}
        self.assertTrue(
            {
                "ARTIFACT",
                "CAPABILITY",
                "WORKPACK",
                "ENGINEERING_PROJECT",
                "ENGINEERING_NODE",
                "RELEASE_STEP",
            }.issubset(node_kinds)
        )
        node_ids = {item["node_id"] for item in graph["nodes"]}
        self.assertTrue(
            {
                "WORKPACK:MB-P3",
                "ENGINEERING_PROJECT:MAIN_HARNESS_BUILD",
                "ENGINEERING_NODE:MAIN_P3_C3_OR_APPROVED_NA",
                "RELEASE_STEP:IMMUTABLE_ARTIFACT_BUILD",
            }.issubset(node_ids)
        )
        edge_keys = {
            (
                item["from_node_id"],
                item["to_node_id"],
                item["edge_kind"],
            )
            for item in graph["edges"]
        }
        self.assertIn(
            (
                "ENGINEERING_PROJECT:MAIN_HARNESS_BUILD",
                "WORKPACK:MB-P3",
                "ENGINEERING_PROJECT_OWNS_WORKPACK",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "RELEASE_STEP:IMMUTABLE_ARTIFACT_BUILD",
                "CAPABILITY:IMMUTABLE_RELEASE_ARTIFACT",
                "RELEASE_STEP_PRODUCES_CAPABILITY",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "ARTIFACT:ART-MB-P3",
                "ARTIFACT:ART-MB-P4",
                "ARTIFACT_REQUIRED_BY_ARTIFACT",
            ),
            edge_keys,
        )

        missing_release_plane = deepcopy(graph)
        missing_release_plane["nodes"] = [
            item
            for item in missing_release_plane["nodes"]
            if item["node_id"] != "RELEASE_STEP:IMMUTABLE_ARTIFACT_BUILD"
        ]
        self.assertIn(
            "COMPOSITE_DEPENDENCY_GRAPH_INVALID",
            {
                finding["code"]
                for finding in validate_composite_dependency_graph(
                    missing_release_plane, artifact_index
                )
            },
        )

    def test_dependency_reads_use_per_job_leases_and_reject_cross_job_root(
        self,
    ) -> None:
        first_obligation = self.ir["atoms"][0]["production_contract"][
            "workpack_obligations"
        ][0]
        first_artifact = first_obligation["artifact_obligations"][0]
        first_artifact["artifact_ref"] = (
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/"
            "p1/architecture_lock.json"
        )
        second_obligation = deepcopy(first_obligation)
        second_obligation["workpack_id"] = "MB-P2"
        second_obligation["completion_rule"] = "P2_RECEIPT_SCHEMA_AND_ORACLE_PASS"
        second_artifact = second_obligation["artifact_obligations"][0]
        second_artifact["artifact_id"] = "P2_RECEIPT"
        second_artifact["artifact_ref"] = (
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/"
            "p2/receipt.json"
        )
        second_artifact["depends_on_artifact_ids"] = ["ARCHITECTURE_LOCK"]
        self.ir["atoms"][0]["production_contract"][
            "workpack_obligations"
        ].append(second_obligation)
        third_obligation = deepcopy(second_obligation)
        third_obligation["workpack_id"] = "MB-P3"
        third_obligation["completion_rule"] = "P3_RECEIPT_SCHEMA_AND_ORACLE_PASS"
        third_artifact = third_obligation["artifact_obligations"][0]
        third_artifact["artifact_id"] = "P3_RECEIPT"
        third_artifact["artifact_ref"] = (
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/"
            "p3/receipt.json"
        )
        third_artifact["depends_on_artifact_ids"] = ["P2_RECEIPT"]
        self.ir["atoms"][0]["production_contract"][
            "workpack_obligations"
        ].append(third_obligation)
        self.ir["coverage_edges"][0]["workpack_ids"] = [
            "MB-P1",
            "MB-P2",
            "MB-P3",
        ]
        self.ir["coverage_edges"][0]["stage_ids"] = ["P1", "P2", "P3"]

        self.compile()

        project_root = self.candidate / "project_start_packages/main_build"
        index = json.loads(
            (project_root / "WORKPACK_INDEX.json").read_text(encoding="utf-8")
        )
        workpack = next(
            item for item in index["workpacks"] if item["workpack_id"] == "MB-P2"
        )
        capsule = json.loads(
            (project_root / "capsules/MB-P2.capsule.json").read_text(
                encoding="utf-8"
            )
        )
        command_path = project_root / "commands/MB-P2.commands.json"
        command_manifest = json.loads(command_path.read_text(encoding="utf-8"))
        coding = next(
            item
            for item in command_manifest["commands"]
            if item["command_id"] == "MB-CODEX-CODING"
        )
        test = next(
            item
            for item in command_manifest["commands"]
            if item["command_id"] == "MB-TEST"
        )
        expected_scope = [
            {
                "job_id": "JOB-SEMANTIC-001",
                "allowed_read_roots": [
                    "harness-resource://execution/jobs/JOB-SEMANTIC-001/p1"
                ],
            }
        ]
        self.assertEqual(workpack["job_artifact_read_scopes"], expected_scope)
        self.assertEqual(capsule["job_artifact_read_scopes"], expected_scope)
        self.assertEqual(coding["job_artifact_read_scopes"], expected_scope)
        self.assertEqual(coding["artifact_read_scope_mode"], "ONE_JOB_LEASE_REQUIRED")
        self.assertTrue(coding["job_artifact_lease_required"])
        lease = coding["job_artifact_lease_contract"]
        selected = lease["receipt_schema"]["oneOf"][0]["properties"]
        self.assertEqual(
            selected["allowed_read_roots"],
            {"const": expected_scope[0]["allowed_read_roots"]},
        )
        self.assertEqual(selected["job_id"], {"const": "JOB-SEMANTIC-001"})
        self.assertEqual(test["job_artifact_read_scopes"], [])
        self.assertEqual(test["artifact_read_scope_mode"], "NONE")

        p3_commands = json.loads(
            (project_root / "commands/MB-P3.commands.json").read_text(
                encoding="utf-8"
            )
        )
        p3_coding = next(
            item
            for item in p3_commands["commands"]
            if item["command_id"] == "MB-CODEX-CODING"
        )
        self.assertEqual(
            p3_coding["job_artifact_read_scopes"],
            [
                {
                    "job_id": "JOB-SEMANTIC-001",
                    "allowed_read_roots": [
                        "harness-resource://execution/jobs/JOB-SEMANTIC-001/p2",
                        "harness-resource://execution/jobs/JOB-SEMANTIC-001/p1",
                    ],
                }
            ],
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

        self.make_candidate_writable()
        p3_command_path = project_root / "commands/MB-P3.commands.json"
        p3_commands = json.loads(p3_command_path.read_text(encoding="utf-8"))
        p3_coding = next(
            item
            for item in p3_commands["commands"]
            if item["command_id"] == "MB-CODEX-CODING"
        )
        p3_coding["job_artifact_read_scopes"][0]["allowed_read_roots"].remove(
            "harness-resource://execution/jobs/JOB-SEMANTIC-001/p1"
        )
        p3_coding["command_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in p3_coding.items()
                    if key != "command_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        p3_commands["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in p3_commands.items()
                    if key != "manifest_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        p3_command_path.write_text(
            json.dumps(p3_commands, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        p3_workpack = next(
            item for item in index["workpacks"] if item["workpack_id"] == "MB-P3"
        )
        p3_workpack["command_manifest_sha256"] = hashlib.sha256(
            p3_command_path.read_bytes()
        ).hexdigest()
        (project_root / "WORKPACK_INDEX.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "PROJECT_WORKPACK_COMMAND_BINDING_INVALID",
            self.finding_codes(),
        )

        command_manifest = json.loads(command_path.read_text(encoding="utf-8"))
        coding = next(
            item
            for item in command_manifest["commands"]
            if item["command_id"] == "MB-CODEX-CODING"
        )
        coding["job_artifact_read_scopes"][0]["allowed_read_roots"] = [
            str(self.execution / "jobs/JOB-CROSS/p1")
        ]
        command_without_hash = dict(coding)
        command_without_hash.pop("command_sha256", None)
        coding["command_sha256"] = hashlib.sha256(
            json.dumps(
                command_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest_without_hash = dict(command_manifest)
        manifest_without_hash.pop("manifest_sha256", None)
        command_manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                manifest_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        command_path.write_text(
            json.dumps(
                command_manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        workpack["command_manifest_sha256"] = hashlib.sha256(
            command_path.read_bytes()
        ).hexdigest()
        (project_root / "WORKPACK_INDEX.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "PROJECT_WORKPACK_COMMAND_BINDING_INVALID",
            self.finding_codes(),
        )

    def test_domain_semantics_route_to_build_phases_before_release(self) -> None:
        routed = normalize_ir_coverage(
            {
                "atoms": [
                    {
                        "atom_id": "ATOM-FUNCTION",
                        "text_or_lossless_paraphrase": (
                            "Reason what the Skill function does, its scenario, effect, and limitations."
                        ),
                        "owner": "MAIN_HARNESS_BUILD",
                        "verification_mode": "CLAIM_MATRIX",
                    },
                    {
                        "atom_id": "ATOM-ALIGNMENT",
                        "text_or_lossless_paraphrase": (
                            "Synthesize local TTS audio and align narration timing to Motion IR."
                        ),
                        "owner": "MAIN_HARNESS_BUILD",
                        "verification_mode": "AUDIO_ALIGNMENT_RECEIPT",
                    },
                    {
                        "atom_id": "ATOM-RENDER",
                        "text_or_lossless_paraphrase": (
                            "Render local animation with Remotion and pinned video-shotcraft."
                        ),
                        "owner": "MAIN_HARNESS_BUILD",
                        "verification_mode": "LOCAL_RENDER_RECEIPT",
                    },
                ]
            }
        )
        edges = {item["atom_id"]: item for item in routed["coverage_edges"]}

        self.assertEqual(edges["ATOM-FUNCTION"]["workpack_ids"], ["MB-P1"])
        self.assertEqual(edges["ATOM-ALIGNMENT"]["workpack_ids"], ["MB-P2"])
        self.assertEqual(edges["ATOM-RENDER"]["workpack_ids"], ["MB-P3"])
        self.assertTrue(
            all(
                "MB-P4" not in edge["workpack_ids"]
                and "MB-RELEASE-CANDIDATE" not in edge["workpack_ids"]
                for edge in edges.values()
            )
        )

    def test_authoring_stop_is_a_historical_g0_handoff_receipt(self) -> None:
        value = deepcopy(self.ir)
        value["atoms"] = [
            {
                "atom_id": "ATOM-AUTHORING",
                "text_or_lossless_paraphrase": (
                    "Verify the AUTHORING_STOP boundary and immutable Candidate handoff."
                ),
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "AUTHORING_STOP_RECEIPT",
                "error_semantics": ["AUTHORING_STOP"],
            }
        ]
        value["coverage_edges"] = normalize_ir_coverage(value)["coverage_edges"]
        value["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        value["target"]["artifact_schema_catalog"] = {
            "ATOM-AUTHORING": {
                "artifact_name": "authoring_stop_receipt",
                "artifact_kind": "AUTHORING_STOP_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["current_state", "status"],
                    "properties": {
                        "current_state": {
                            "const": "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW"
                        },
                        "status": {"const": "PASS"},
                    },
                },
            }
        }

        compiled = compile_declared_production_contracts(value)
        edge = compiled["coverage_edges"][0]
        artifact = compiled["atoms"][0]["production_contract"][
            "workpack_obligations"
        ][0]["artifact_obligations"][0]

        self.assertEqual(edge["workpack_ids"], ["MB-G0"])
        self.assertEqual(edge["stage_ids"], ["G0"])
        self.assertIn(
            "candidate_human_review_closure_sha256",
            artifact["schema"]["required"],
        )
        self.assertNotIn("current_state", artifact["schema"]["properties"])
        self.assertFalse(
            artifact["schema"]["properties"]["authoring_workpack_started"][
                "const"
            ]
        )

    def test_video_pipeline_has_single_phase_and_complete_media_lineage(self) -> None:
        value = deepcopy(self.ir)

        def atom(atom_id: str, verification_mode: str, text: str) -> dict:
            return {
                "atom_id": atom_id,
                "text_or_lossless_paraphrase": text,
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": verification_mode,
                "error_semantics": [f"{atom_id}_INVALID"],
            }

        value["atoms"] = [
            atom("ATOM-SOURCE", "SOURCE_FREEZE_RECEIPT", "Freeze one Skill source."),
            atom("ATOM-FUNCTION", "FUNCTION_SCENARIO_EFFECT_MATRIX", "Bind function and scenario claims."),
            atom("ATOM-ASSET", "ASSET_PLAN", "Route every visual asset."),
            atom("ATOM-DEMO", "BEFORE_AFTER_DEMO_CONTRACT", "Bind a before and after demonstration."),
            atom("ATOM-TTS", "LOCAL_TTS_RECEIPT", "Synthesize local narration."),
            atom("ATOM-ALIGN", "AUDIO_ALIGNMENT_RECEIPT", "Align narration anchors."),
            atom("ATOM-MOTION", "OBJECT_MOTION_IR", "Compile object motion against audio anchors."),
            atom("ATOM-GATE", "TARGET_SKILL_EXECUTION_GATE_RECEIPT", "Keep target Skill execution default off."),
            atom("ATOM-RENDER", "LOCAL_RENDER_RECEIPT", "Render locally with video-shotcraft."),
            atom("ATOM-MEDIA", "MEDIA_ACCEPTANCE_RECEIPT", "Probe and accept the final video bytes."),
        ]
        value["coverage_edges"] = normalize_ir_coverage(value)["coverage_edges"]
        value["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )

        def basic_schema() -> dict:
            return {
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"const": "PASS"}},
            }

        catalog = {
            item["atom_id"]: {
                "artifact_kind": item["verification_mode"],
                "schema": basic_schema(),
            }
            for item in value["atoms"]
        }
        catalog["ATOM-ASSET"]["schema"] = {
            "type": "object",
            "required": [
                "route",
                "local_build_recipe",
                "generation_authorization_ref",
                "status",
            ],
            "properties": {
                "route": {
                    "enum": [
                        "SOURCE_EVIDENCE",
                        "CODEX_IMAGEGEN",
                        "LOCAL_PY_DETERMINISTIC",
                    ]
                },
                "local_build_recipe": {"type": ["object", "null"]},
                "generation_authorization_ref": {"type": ["string", "null"]},
                "status": {"const": "PASS"},
            },
        }
        catalog["ATOM-ALIGN"]["schema"] = {
            "type": "object",
            "required": ["sentence_ids", "word_anchors", "status"],
            "properties": {
                "sentence_ids": {"type": "array"},
                "word_anchors": {"type": "array"},
                "status": {"const": "PASS"},
            },
        }
        catalog["ATOM-MOTION"]["schema"] = {
            "type": "object",
            "required": ["audio_anchor_ids", "objects", "status"],
            "properties": {
                "audio_anchor_ids": {"type": "array"},
                "objects": {"type": "array", "items": {"type": "object"}},
                "status": {"const": "PASS"},
            },
        }
        value["target"]["artifact_schema_catalog"] = catalog

        compiled = compile_declared_production_contracts(value)
        edges = {
            item["atom_id"]: item["workpack_ids"]
            for item in compiled["coverage_edges"]
        }
        artifacts = {
            artifact["artifact_kind"]: artifact
            for item in compiled["atoms"]
            for obligation in item["production_contract"]["workpack_obligations"]
            for artifact in obligation["artifact_obligations"]
        }

        self.assertEqual(edges["ATOM-ASSET"], ["MB-P1"])
        self.assertEqual(edges["ATOM-DEMO"], ["MB-P2"])
        self.assertEqual(edges["ATOM-MOTION"], ["MB-P2"])
        self.assertEqual(edges["ATOM-RENDER"], ["MB-P3"])
        alignment_schema = artifacts["AUDIO_ALIGNMENT_RECEIPT"]["schema"]
        self.assertNotIn("final_av_drift_frames", alignment_schema["required"])
        self.assertNotIn(
            "absolute_final_av_drift_frames", alignment_schema["required"]
        )
        self.assertNotIn(
            "ABSOLUTE_FINAL_AV_DRIFT_EQUALS_ABS_FINAL_AV_DRIFT",
            alignment_schema["x-invariants"],
        )
        self.assertNotIn(
            "AUDIO_VIDEO_DRIFT",
            {
                item["error_code"]
                for item in artifacts["AUDIO_ALIGNMENT_RECEIPT"][
                    "failure_returns"
                ]
            },
        )
        self.assertEqual(
            artifacts["AUDIO_ALIGNMENT_RECEIPT"]["oracle"]["decision_rule"],
            (
                "Recompute word anchors from synthesized audio and verify "
                "anchor ordering, audio hashes, opening dead air, and "
                "alignment error thresholds."
            ),
        )
        motion_schema = artifacts["OBJECT_MOTION_IR"]["schema"]
        self.assertEqual(
            motion_schema["properties"]["word_to_motion_tolerance_seconds"],
            {"const": 0.1},
        )
        self.assertEqual(
            motion_schema["properties"]["shots"]["minItems"], 10
        )
        self.assertEqual(
            motion_schema["properties"]["shots"]["maxItems"], 14
        )
        self.assertEqual(
            motion_schema["properties"]["scene_transition_count"],
            {"type": "integer", "minimum": 9, "maximum": 13},
        )
        motion_sync_invariant = (
            "EVERY_OBJECT_WORD_TO_MOTION_ERROR_DOES_NOT_EXCEED_0_1_SECONDS"
        )
        self.assertIn(motion_sync_invariant, motion_schema["x-invariants"])
        motion_sync_contract = motion_schema["x-invariant-contracts"][
            motion_sync_invariant
        ]
        self.assertEqual(
            motion_sync_contract["algorithm"],
            (
                "FOR_EACH_OBJECT_RESOLVE_AUDIO_ANCHOR_START_SECONDS_AND_"
                "REQUIRE_ABS_OBJECT_ENTER_TIME_MINUS_ANCHOR_START_SECONDS_"
                "LTE_WORD_TO_MOTION_TOLERANCE_SECONDS"
            ),
        )
        self.assertEqual(
            motion_sync_contract["failure_code"],
            "MOTION_SYNC_TOLERANCE_EXCEEDED",
        )
        self.assertIn(
            artifacts["TARGET_SKILL_EXECUTION_GATE_RECEIPT"]["artifact_id"],
            artifacts["BEFORE_AFTER_DEMO_CONTRACT"][
                "depends_on_artifact_ids"
            ],
        )
        self.assertEqual(
            artifacts["LOCAL_RENDER_RECEIPT"]["depends_on_artifact_ids"],
            [
                "ART-ATOM-SOURCE-MB-P1",
                "ART-ATOM-FUNCTION-MB-P1",
                "ART-ATOM-TTS-MB-P2-NARRATION-SCRIPT",
                "ART-ATOM-TTS-MB-P2",
                "ART-ATOM-ALIGN-MB-P2",
                "ART-ATOM-MOTION-MB-P2",
                "ART-ATOM-ASSET-MB-P1",
                "ART-ATOM-MOTION-MB-P2-ASSET-BINDING-RECEIPT",
                "ART-ATOM-DEMO-MB-P2",
                "ART-ATOM-GATE-MB-P2",
            ],
        )
        self.assertEqual(
            artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["depends_on_artifact_ids"],
            [
                "ART-ATOM-RENDER-MB-P3",
                "ART-ATOM-TTS-MB-P2-NARRATION-SCRIPT",
                "ART-ATOM-TTS-MB-P2",
                "ART-ATOM-ALIGN-MB-P2",
                "ART-ATOM-MOTION-MB-P2",
                "ART-ATOM-ASSET-MB-P1",
                "ART-ATOM-MOTION-MB-P2-ASSET-BINDING-RECEIPT",
                "ART-ATOM-DEMO-MB-P2",
                "ART-ATOM-SOURCE-MB-P1",
                "ART-ATOM-FUNCTION-MB-P1",
                "ART-ATOM-GATE-MB-P2",
            ],
        )
        self.assertIn(
            "oneOf",
            artifacts["ASSET_PLAN"]["schema"]["properties"]["assets"]["items"],
        )
        asset_item = artifacts["ASSET_PLAN"]["schema"]["properties"][
            "assets"
        ]["items"]
        asset_required = set(asset_item["required"])
        self.assertTrue(
            {
                "asset_ref",
                "asset_sha256",
                "provenance_refs",
                "provenance_sha256s",
                "local_build_recipe",
                "generation_receipt_ref",
                "generation_receipt_sha256",
            }.issubset(asset_required)
        )
        self.assertIn(
            "EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256",
            artifacts["ASSET_PLAN"]["schema"]["x-invariants"],
        )
        self.assertIn(
            "oneOf", artifacts["TARGET_SKILL_EXECUTION_GATE_RECEIPT"]["schema"]
        )
        demo_schema = artifacts["BEFORE_AFTER_DEMO_CONTRACT"]["schema"]
        self.assertTrue(
            {
                "input_before_sha256",
                "output_after_sha256",
                "source_evidence_refs",
                "source_evidence_sha256s",
                "target_skill_authorization_ref",
                "target_skill_execution_receipt_ref",
                "target_skill_execution_receipt_sha256",
                "actual_skill_output",
                "illustration_label",
                "effect_claim_id",
                "effect_delta",
            }.issubset(demo_schema["required"])
        )
        self.assertIn(
            "DEMO_INPUT_AND_OUTPUT_BYTES_ARE_DISTINCT",
            demo_schema["x-invariants"],
        )
        self.assertIn(
            "DEMO_EFFECT_DELTA_CONTAINS_OBSERVED_STATE_CHANGE",
            demo_schema["x-invariants"],
        )
        effect_delta_item = demo_schema["properties"]["effect_delta"]["items"]
        self.assertTrue(
            {
                "property_path",
                "before_value",
                "after_value",
                "evidence_ref",
                "evidence_sha256",
                "evidence_input_sha256",
                "evidence_output_sha256",
                "observed_change",
            }.issubset(effect_delta_item["required"])
        )
        self.assertEqual(
            effect_delta_item["properties"]["property_path"]["pattern"],
            "^(?:/(?:[^~/]|~0|~1)*)+$",
        )
        demo_delta_invariants = {
            "DEMO_EFFECT_DELTA_PROPERTY_PATHS_RESOLVE_IN_BOTH_STATES",
            "DEMO_EFFECT_DELTA_VALUES_EQUAL_RESOLVED_STATE_VALUES",
            "DEMO_EFFECT_DELTA_BEFORE_AND_AFTER_VALUES_ARE_DISTINCT",
            "DEMO_EFFECT_DELTA_EVIDENCE_SHA256_MATCHES_REFERENCED_BYTES",
            "DEMO_EFFECT_DELTA_EVIDENCE_BINDS_BEFORE_AND_AFTER_BYTES",
        }
        self.assertTrue(
            demo_delta_invariants.issubset(demo_schema["x-invariants"])
        )
        self.assertEqual(
            set(demo_schema["x-invariant-contracts"]),
            set(demo_schema["x-invariants"]),
        )
        self.assertTrue(
            all(
                contract["algorithm"] and contract["failure_code"]
                for contract in demo_schema["x-invariant-contracts"].values()
            )
        )
        demo_branches = {
            branch["properties"]["provenance_state"]["const"]: branch
            for branch in demo_schema["oneOf"]
        }
        authorized_demo = demo_branches["AUTHORIZED_TARGET_SKILL_RUN"]
        self.assertEqual(
            authorized_demo["properties"]["target_skill_authorization_ref"][
                "type"
            ],
            "string",
        )
        self.assertEqual(
            authorized_demo["properties"][
                "target_skill_execution_receipt_ref"
            ]["type"],
            "string",
        )
        illustration_demo = demo_branches["CLEARLY_LABELED_ILLUSTRATION"]
        self.assertFalse(
            illustration_demo["properties"]["actual_skill_output"]["const"]
        )
        self.assertTrue(
            {
                "audio_sha256",
                "render_input_manifest_ref",
                "render_input_manifest_sha256",
                "composition_ref",
                "composition_sha256",
                "render_command_receipt_ref",
                "render_command_receipt_sha256",
                "tts_receipt_ref",
                "tts_receipt_sha256",
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "dependency_manifest_ref",
                "dependency_manifest_sha256",
            }.issubset(
                artifacts["LOCAL_RENDER_RECEIPT"]["schema"]["required"]
            )
        )
        self.assertTrue(
            {
                "video_ref",
                "video_sha256",
                "ffprobe_receipt_ref",
                "ffprobe_receipt_sha256",
                "render_receipt_ref",
                "render_receipt_sha256",
                "tts_receipt_ref",
                "tts_receipt_sha256",
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "dependency_manifest_ref",
                "dependency_manifest_sha256",
            }.issubset(
                artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["schema"]["required"]
            )
        )
        self.assertEqual(
            artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["schema"]["properties"][
                "audio_stream_count"
            ]["minimum"],
            1,
        )

    def test_validator_rejects_phase_impossible_alignment_evidence(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
            )
        )
        self.compile()
        self.make_candidate_writable()

        frozen_path = self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        alignment = next(
            artifact
            for atom in frozen["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
            if artifact["artifact_kind"] == "AUDIO_ALIGNMENT_RECEIPT"
        )
        alignment["schema"]["required"].append("final_av_drift_frames")
        alignment["schema"]["properties"]["final_av_drift_frames"] = {
            "type": "number"
        }
        frozen_path.write_text(
            json.dumps(frozen, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "ARTIFACT_PHASE_EVIDENCE_CONTRACT_INVALID", self.finding_codes()
        )

    def test_validator_rejects_alignment_future_stage_oracle(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
            )
        )
        self.compile()
        self.make_candidate_writable()

        frozen_path = self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        alignment = next(
            artifact
            for atom in frozen["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
            if artifact["artifact_kind"] == "AUDIO_ALIGNMENT_RECEIPT"
        )
        alignment["failure_returns"].append(
            {
                "error_code": "AUDIO_VIDEO_DRIFT",
                "control_node_id": "MB-P2",
                "invalidates": "CURRENT_ARTIFACT_AND_DEPENDENT_RECEIPTS",
            }
        )
        alignment["oracle"]["decision_rule"] = (
            "Compare Motion IR anchors and final stream duration."
        )
        frozen_path.write_text(
            json.dumps(frozen, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "ARTIFACT_PHASE_EVIDENCE_CONTRACT_INVALID", self.finding_codes()
        )

    def test_validator_rejects_motion_sync_and_cadence_weakening(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
            )
        )
        self.compile()
        self.make_candidate_writable()

        frozen_path = self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        motion = next(
            artifact
            for atom in frozen["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
            if artifact["artifact_kind"] == "OBJECT_MOTION_IR"
        )
        motion["schema"]["properties"]["shots"]["minItems"] = 2
        motion["schema"]["properties"]["scene_transition_count"][
            "minimum"
        ] = 1
        motion_sync_invariant = (
            "EVERY_OBJECT_WORD_TO_MOTION_ERROR_DOES_NOT_EXCEED_0_1_SECONDS"
        )
        if motion_sync_invariant in motion["schema"]["x-invariants"]:
            motion["schema"]["x-invariants"].remove(motion_sync_invariant)
        frozen_path.write_text(
            json.dumps(frozen, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        codes = self.finding_codes()
        self.assertIn("MOTION_SYNC_CONTRACT_INCOMPLETE", codes)
        self.assertIn("VIDEO_CADENCE_CONTRACT_INCOMPLETE", codes)

    def test_validator_rejects_unreachable_authorized_demo_branch(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
            )
        )
        self.compile()
        self.make_candidate_writable()

        frozen_path = self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        demo = next(
            artifact
            for atom in frozen["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
            if artifact["artifact_kind"] == "BEFORE_AFTER_DEMO_CONTRACT"
        )
        gate_ids = {
            artifact["artifact_id"]
            for atom in frozen["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
            if artifact["artifact_kind"]
            == "TARGET_SKILL_EXECUTION_GATE_RECEIPT"
        }
        demo["depends_on_artifact_ids"] = [
            artifact_id
            for artifact_id in demo["depends_on_artifact_ids"]
            if artifact_id not in gate_ids
        ]
        frozen_path.write_text(
            json.dumps(frozen, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "AUTHORIZED_DEMO_BRANCH_UNREACHABLE", self.finding_codes()
        )

    def test_validator_rejects_asset_render_lineage_contract_weakening(
        self,
    ) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "LOCAL_RENDER_RECEIPT",
                "MEDIA_ACCEPTANCE_RECEIPT",
            )
        )
        self.compile()
        self.make_candidate_writable()

        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        render = next(
            item
            for item in manifest["artifact_index"].values()
            if item["artifact_kind"] == "LOCAL_RENDER_RECEIPT"
        )
        render["schema"]["required"].remove("render_command_receipt_sha256")
        manifest_without_hash = dict(manifest)
        manifest_without_hash.pop("manifest_sha256", None)
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                manifest_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "ARTIFACT_BYTE_LINEAGE_CONTRACT_INCOMPLETE",
            self.finding_codes(),
        )

    def test_validator_rejects_underdetermined_demo_effect_delta(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
            )
        )
        self.compile()
        self.make_candidate_writable()

        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        demo = next(
            item
            for item in manifest["artifact_index"].values()
            if item["artifact_kind"] == "BEFORE_AFTER_DEMO_CONTRACT"
        )
        delta_item = demo["schema"]["properties"]["effect_delta"]["items"]
        delta_item["properties"]["property_path"] = {
            "type": "string",
            "minLength": 1,
        }
        manifest_without_hash = dict(manifest)
        manifest_without_hash.pop("manifest_sha256", None)
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                manifest_without_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "DEMO_EFFECT_DELTA_CONTRACT_INCOMPLETE",
            self.finding_codes(),
        )

    def test_terminal_media_validation_follows_local_render(self) -> None:
        value = deepcopy(self.ir)
        value["atoms"] = [
            {
                "atom_id": "ATOM-ALIGN",
                "text_or_lossless_paraphrase": "Force-align local narration audio.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "WORD_ANCHOR_SYNC_RECEIPT",
            },
            {
                "atom_id": "ATOM-MOTION",
                "text_or_lossless_paraphrase": "Compile object-level Motion IR.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "MOTION_IR_SCHEMA_AND_RENDER_TRACE",
            },
            {
                "atom_id": "ATOM-RENDER",
                "text_or_lossless_paraphrase": "Render the final animation locally.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "PINNED_DEPENDENCY_MANIFEST_AND_LOCAL_RENDER_RECEIPT",
                "compatibility_constraints": ["Pinned commit " + "1" * 40],
            },
            {
                "atom_id": "ATOM-MEDIA",
                "text_or_lossless_paraphrase": "Probe the final video bytes.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "MEDIA_PROBE_AND_DURATION_RECEIPT",
                "error_semantics": ["TTS_DURATION_DRIFT"],
            },
        ]
        value["acceptance_cases"] = [
            {
                "case_id": "AC-TERMINAL-MEDIA",
                "atom_ids": [
                    "ATOM-ALIGN",
                    "ATOM-MOTION",
                    "ATOM-RENDER",
                    "ATOM-MEDIA",
                ],
                "description": "Probe and accept the final rendered video bytes.",
                "evidence_type": "MEDIA_PROBE_AND_DURATION_RECEIPT",
            }
        ]
        value["negative_cases"] = [
            {
                "case_id": "NEG-TERMINAL-MEDIA-DURATION",
                "atom_ids": ["ATOM-MEDIA"],
                "description": "Reject final media outside the duration contract.",
                "expected_failure": "TTS_DURATION_DRIFT",
            }
        ]
        value["coverage_edges"] = []
        value["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        value["target"]["artifact_schema_catalog"] = {
            "ATOM-ALIGN": {
                "artifact_kind": "AUDIO_ALIGNMENT_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["sentence_ids", "word_anchors", "status"],
                    "properties": {
                        "sentence_ids": {"type": "array", "minItems": 1},
                        "word_anchors": {"type": "array", "minItems": 1},
                        "status": {"const": "PASS"},
                    },
                },
            },
            "ATOM-MOTION": {
                "artifact_kind": "OBJECT_MOTION_IR",
                "schema": {
                    "type": "object",
                    "required": ["audio_anchor_ids", "objects", "status"],
                    "properties": {
                        "audio_anchor_ids": {"type": "array", "minItems": 1},
                        "objects": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "required": [
                                    "object_id",
                                    "geometry",
                                    "enter_time",
                                    "hold_interval",
                                    "exit_time",
                                    "motion_curve",
                                    "audio_anchor_id",
                                ],
                            },
                        },
                        "status": {"const": "PASS"},
                    },
                },
            },
            "ATOM-RENDER": {
                "artifact_kind": "LOCAL_RENDER_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["video_ref", "status"],
                    "properties": {
                        "video_ref": {"type": "string"},
                        "status": {"const": "PASS"},
                    },
                },
            },
            "ATOM-MEDIA": {
                "artifact_kind": "MEDIA_ACCEPTANCE_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["video_ref", "status"],
                    "properties": {
                        "video_ref": {"type": "string"},
                        "status": {"const": "PASS"},
                    },
                },
            },
        }

        routed = normalize_ir_coverage(value)
        edges = {item["atom_id"]: item for item in routed["coverage_edges"]}
        self.assertEqual(edges["ATOM-RENDER"]["workpack_ids"], ["MB-P3"])
        self.assertEqual(edges["ATOM-MEDIA"]["workpack_ids"], ["MB-P3"])

        compiled = compile_declared_production_contracts(routed)
        all_artifacts = {
            artifact["artifact_kind"]: artifact
            for atom in compiled["atoms"]
            for obligation in atom["production_contract"]["workpack_obligations"]
            for artifact in obligation["artifact_obligations"]
        }
        artifacts = {
            artifact["artifact_kind"]: artifact
            for atom in compiled["atoms"]
            for obligation in atom["production_contract"]["workpack_obligations"]
            if obligation["workpack_id"] == "MB-P3"
            for artifact in obligation["artifact_obligations"]
        }
        self.assertEqual(
            artifacts["LOCAL_RENDER_RECEIPT"]["depends_on_artifact_ids"],
            [
                "ART-ATOM-ALIGN-MB-P2",
                "ART-ATOM-MOTION-MB-P2",
                "ART-ATOM-MOTION-MB-P2-ASSET-BINDING-RECEIPT",
            ],
        )
        self.assertEqual(
            artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["depends_on_artifact_ids"],
            [
                "ART-ATOM-RENDER-MB-P3",
                "ART-ATOM-ALIGN-MB-P2",
                "ART-ATOM-MOTION-MB-P2",
                "ART-ATOM-MOTION-MB-P2-ASSET-BINDING-RECEIPT",
            ],
        )
        self.assertIn(
            "video_sha256",
            artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["schema"]["required"],
        )
        self.assertTrue(
            all_artifacts["OBJECT_MOTION_IR"]["schema"]["properties"]["shots"]
            ["items"]["properties"]["objects"]["items"]["properties"]
        )
        self.assertIsNotNone(
            all_artifacts["AUDIO_ALIGNMENT_RECEIPT"]["schema"]["properties"][
                "word_anchors"
            ]["items"]
        )

        self.ir = routed
        self.compile()
        report = validate_candidate(self.candidate)
        self.assertEqual(report["status"], "PASS", report["blocking_findings"])

        self.make_candidate_writable()
        coverage_path = (
            self.candidate / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
        )
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        media_row = next(
            item
            for item in coverage["coverage"]
            if item["atom_id"] == "ATOM-MEDIA"
        )
        media_row["workpack_ids"] = ["MB-P2"]
        media_row["stage_ids"] = ["P2"]
        coverage_path.write_text(
            json.dumps(coverage, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "SEMANTIC_PHASE_ROUTING_INVALID",
            self.finding_codes(),
        )

    def test_external_lab_fixture_semantics_do_not_require_main_build_phases(
        self,
    ) -> None:
        atom = self.ir["atoms"][0]
        atom.update(
            {
                "owner": "EXTERNAL_CONFORMANCE_LAB",
                "text_or_lossless_paraphrase": (
                    "Exercise an independent video rendering fixture in the external lab."
                ),
                "verification_mode": "INDEPENDENT_FIXTURE_ACCEPTANCE",
                "order_constraints": ["implementation before fixture acceptance"],
            }
        )
        del atom["production_contract"]
        self.ir["coverage_edges"] = normalize_ir_coverage(
            {"atoms": [atom]}
        )["coverage_edges"]
        self.ir["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        self.ir["target"]["artifact_schema_catalog"] = {
            "ATOM-001": {
                "artifact_name": "external_fixture_result",
                "artifact_kind": "FIXTURE_ACCEPTANCE_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["fixture_id", "status"],
                    "properties": {
                        "fixture_id": {"type": "string"},
                        "status": {"const": "PASS"},
                    },
                },
            }
        }

        self.compile()

        frozen = json.loads(
            (
                self.candidate
                / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
            ).read_text(encoding="utf-8")
        )
        edge = frozen["coverage_edges"][0]
        self.assertEqual(edge["workpack_ids"], ["LAB-CERTIFICATION"])
        self.assertNotIn("MB-P3", edge["workpack_ids"])
        manifest = json.loads(
            (
                self.candidate
                / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        artifact = next(iter(manifest["artifact_index"].values()))
        self.assertEqual(
            artifact["artifact_kind"], "FIXTURE_ACCEPTANCE_RECEIPT"
        )
        self.assertTrue(
            artifact["schema"]["properties"]["execution_started"]["const"]
        )
        self.assertEqual(
            artifact["schema"]["properties"]["status"]["const"], "PASS"
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_derived_contract_is_recompiled_when_producer_routing_changes(self) -> None:
        value = deepcopy(self.ir)
        value["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        value["atoms"][0]["production_contract"]["derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        value["atoms"][0]["production_contract"]["workpack_obligations"][0][
            "workpack_id"
        ] = "MB-P4"

        compiled = compile_declared_production_contracts(value)
        obligation = compiled["atoms"][0]["production_contract"][
            "workpack_obligations"
        ][0]

        self.assertEqual(obligation["workpack_id"], "MB-P1")

    def test_missing_task_bundle_is_rejected(self) -> None:
        self.compile()
        self.make_candidate_writable()
        (
            self.candidate
            / "project_start_packages/main_build/task_bundles/MB-P1.task_bundle.json"
        ).unlink()
        self.assertIn("TASK_BUNDLE_CONTENT_MISMATCH", self.finding_codes())

    def test_validator_rejects_stale_lab_cli_subcommand_count(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = (
            self.candidate
            / "project_start_packages/external_lab/task_bundles/"
            "LAB-CLI.task_bundle.json"
        )
        bundle = json.loads(path.read_text(encoding="utf-8"))
        obligations = bundle["lab_case_execution_contract"][
            "implementation_obligations"
        ]
        self.assertEqual(
            obligations[0],
            "Expose all seven required subcommands with their declared parameter contracts.",
        )
        obligations[0] = (
            "Expose three required subcommands with their declared parameter contracts."
        )
        path.write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn("TASK_BUNDLE_CONTENT_MISMATCH", self.finding_codes())

    def test_semantic_mode_rejects_label_only_atom(self) -> None:
        del self.ir["atoms"][0]["production_contract"]
        with self.assertRaisesRegex(ValueError, "PRODUCTION_CONTRACT_MISSING"):
            self.compile()

    def test_declared_schema_catalog_deterministically_hydrates_contract(self) -> None:
        del self.ir["atoms"][0]["production_contract"]
        self.ir["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        self.ir["target"]["artifact_schema_catalog"] = {
            "ATOM-001": {
                "artifact_name": "runtime_driver_separation",
                "artifact_kind": "ENTRYPOINT_SEPARATION_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["runtime_entrypoint", "driver_entrypoint"],
                    "properties": {
                        "runtime_entrypoint": {"type": "string"},
                        "driver_entrypoint": {"type": "string"},
                    },
                },
            }
        }

        self.compile()

        frozen = json.loads(
            (
                self.candidate
                / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
            ).read_text(encoding="utf-8")
        )
        contract = frozen["atoms"][0]["production_contract"]
        artifact = contract["workpack_obligations"][0][
            "artifact_obligations"
        ][0]
        self.assertEqual(
            contract["derivation_policy"], DETERMINISTIC_DERIVATION_POLICY
        )
        self.assertEqual(
            artifact["schema"]["required"],
            ["runtime_entrypoint", "driver_entrypoint"],
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_acceptance_fixture_binds_sources_artifacts_and_result_assertions(
        self,
    ) -> None:
        source = self.ir["sources"][0]
        source.update(
            {
                "repository_url": "https://github.com/example/example-skill",
                "revision": "main",
                "commit_sha": "1" * 40,
                "git_tree_oid": "2" * 40,
                "tree_sha256": source["sha256"],
                "license_spdx": "MIT",
            }
        )

        self.compile()

        acceptance = json.loads(
            (self.candidate / "validation/ACCEPTANCE_CASES.json").read_text(
                encoding="utf-8"
            )
        )
        case = acceptance["cases"][0]
        fixture = json.loads(
            (
                self.candidate
                / case["fixture_ref"].removeprefix(
                    "harness-resource://candidate/"
                )
            ).read_text(encoding="utf-8")
        )
        result_schema = json.loads(
            (
                self.candidate / "validation/schemas/CASE_RESULT.schema.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            fixture["input"]["fixture_jobs"][0]["commit_sha"], "1" * 40
        )
        self.assertEqual(
            fixture["input"]["artifact_expectations"][0]["artifact_id"],
            "ARCHITECTURE_LOCK",
        )
        self.assertIn(
            "ALL_ARTIFACTS_SCHEMA_HASH_AND_ORACLE_PASS",
            {item["operator"] for item in fixture["assertions"]},
        )
        assertion_items = result_schema["properties"]["assertion_results"][
            "items"
        ]
        self.assertIn("passed", assertion_items["required"])
        self.assertIn("evidence_refs", assertion_items["required"])
        evidence_assertion = next(
            item
            for item in case["assertions"]
            if item["operator"] == "VALIDATED_RECEIPT_EXISTS"
        )
        fixture_evidence_assertion = next(
            item
            for item in fixture["assertions"]
            if item["operator"] == "VALIDATED_RECEIPT_EXISTS"
        )
        self.assertEqual(evidence_assertion["actual_ref"], case["result_ref"])
        self.assertEqual(
            fixture_evidence_assertion["actual_ref"], case["result_ref"]
        )
        self.assertIn("case_kind", result_schema["required"])
        self.assertFalse(result_schema["additionalProperties"])
        self.assertGreaterEqual(len(result_schema["allOf"]), 3)
        self.assertEqual(
            fixture["input"]["required_artifact_kinds"],
            sorted(
                {
                    item["artifact_kind"]
                    for item in fixture["input"]["artifact_expectations"]
                }
            ),
        )
        self.assertEqual(
            fixture["input"]["evidence_closure_policy"],
            "ALL_CASE_BOUND_ARTIFACT_KINDS_REQUIRED",
        )

    def test_compiled_schema_and_oracle_registry_are_idempotent(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "LOCAL_RENDER_RECEIPT",
                "MEDIA_ACCEPTANCE_RECEIPT",
            )
        )

        compiled_once = compile_declared_production_contracts(self.ir)
        compiled_twice = compile_declared_production_contracts(compiled_once)
        artifacts_once = [
            artifact
            for atom in compiled_once["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
        ]
        artifacts_twice = [
            artifact
            for atom in compiled_twice["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
        ]

        self.assertEqual(compiled_once, compiled_twice)
        self.assertEqual(
            oracle_evaluator_registry(
                {item["artifact_kind"] for item in artifacts_once},
                artifacts_once,
            ),
            oracle_evaluator_registry(
                {item["artifact_kind"] for item in artifacts_twice},
                artifacts_twice,
            ),
        )

    def test_every_invariant_has_typed_executable_contract(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "NARRATION_SCRIPT",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "ASSET_BINDING_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "LOCAL_RENDER_RECEIPT",
                "MEDIA_ACCEPTANCE_RECEIPT",
                "RESUMABLE_STAGE_RECEIPT",
            )
        )
        self.compile()
        artifact_manifest = json.loads(
            (
                self.candidate
                / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        artifacts = list(artifact_manifest["artifact_index"].values())
        required_fields = {
            "algorithm_id",
            "algorithm_version",
            "algorithm",
            "input_refs",
            "target_ref",
            "canonicalization",
            "ordering",
            "numeric_tolerance",
            "branch_precondition",
            "decision_rule",
            "failure_code",
            "quantifier",
            "subject_selector",
            "operand_refs",
            "operand_types",
            "cardinality",
            "join_keys",
            "evaluation_contract_kind",
            "evaluator_entrypoint",
            "predicate_ast",
        }
        contracts_by_kind: dict[str, dict[str, dict]] = {}
        for artifact in artifacts:
            schema = artifact["schema"]
            invariants = set(schema.get("x-invariants", []))
            contracts = schema.get("x-invariant-contracts")
            self.assertEqual(set(contracts or {}), invariants)
            for invariant_id, contract in (contracts or {}).items():
                self.assertTrue(required_fields.issubset(contract))
                self.assertTrue(contract["input_refs"])
                # A negative Case edits one field; the operator may compare an
                # entire collection or paired inputs in a different order.
                self.assertTrue(_schema_declares_json_pointer(schema, contract["target_ref"]))
                self.assertFalse(registered_operator_findings(contract["predicate_ast"]))
                self.assertIn(contract["quantifier"], {"SINGLE", "FOR_ALL"})
                self.assertTrue(contract["subject_selector"])
                self.assertTrue(contract["operand_refs"])
                self.assertEqual(
                    len(contract["operand_types"]),
                    len(contract["operand_refs"]),
                )
                self.assertEqual(
                    contract["cardinality"]["operand_count"],
                    len(contract["operand_refs"]),
                )
                self.assertNotIn("predicate_sha256", contract)
                self.assertFalse(
                    {
                        "artifact://self",
                        "manifest://declared-artifact-dependencies",
                        "evidence://declared-reference-bytes",
                    }.intersection(contract["operand_refs"])
                )
                self.assertEqual(
                    contract["evaluator_entrypoint"],
                    "external_lab.invariants:evaluate_predicate_ast_v1",
                )
                self.assertEqual(
                    contract["predicate_ast"]["subject_selector"],
                    contract["subject_selector"],
                )
                if contract["quantifier"] == "SINGLE":
                    self.assertNotIn("*", contract["subject_selector"])
                else:
                    self.assertIn("*", contract["subject_selector"])
                contracts_by_kind.setdefault(
                    artifact["artifact_kind"], {}
                )[invariant_id] = contract

        narration = contracts_by_kind["NARRATION_SCRIPT"][
            "NARRATION_BUDGET_ESTIMATE_MATCHES_CANONICAL_SENTENCE_ARRAY_AND_METHOD"
        ]
        self.assertEqual(
            narration["algorithm"], "MANDARIN_CHARACTER_RATE_V1"
        )
        self.assertEqual(narration["numeric_tolerance"]["absolute_seconds"], 0.001)
        self.assertIn("unicode_normalization", narration["parameters"])

        render_trace = contracts_by_kind["LOCAL_RENDER_RECEIPT"][
            "RENDER_TRACE_SAMPLES_MATCH_DECLARED_OBJECT_CURVES"
        ]
        self.assertEqual(render_trace["parameters"]["sample_rate_fps"], 30)
        self.assertEqual(
            set(render_trace["parameters"]["easing_functions"]),
            {"LINEAR", "EASE_IN", "EASE_OUT", "EASE_IN_OUT", "SPRING"},
        )

        registry = oracle_evaluator_registry(
            {item["artifact_kind"] for item in artifacts}, artifacts
        )
        for case in registry["invariant_negative_case_matrix"]:
            contract = contracts_by_kind[case["artifact_kind"]][
                case["invariant_id"]
            ]
            expected_hash = hashlib.sha256(
                json.dumps(
                    contract,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(case["invariant_contract_sha256"], expected_hash)
            self.assertEqual(
                case["invariant_contract"], contract
            )

    def test_every_invariant_contract_is_semantically_satisfiable(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "NARRATION_SCRIPT",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "ASSET_BINDING_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "LOCAL_RENDER_RECEIPT",
                "MEDIA_ACCEPTANCE_RECEIPT",
                "RESUMABLE_STAGE_RECEIPT",
            )
        )
        compiled = compile_declared_production_contracts(self.ir)
        artifacts = [
            artifact
            for atom in compiled["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
        ]

        for artifact in artifacts:
            schema = artifact["schema"]
            contracts = schema.get("x-invariant-contracts", {})
            for invariant_id, contract in contracts.items():
                with self.subTest(
                    artifact_kind=artifact["artifact_kind"],
                    invariant_id=invariant_id,
                ):
                    for operand_ref in contract["operand_refs"]:
                        self.assertTrue(
                            schema_declares_pointer(schema, operand_ref),
                            operand_ref,
                        )
                    if contract["algorithm"] == (
                        "CANONICAL_VALUE_OR_SET_EQUALITY_V1"
                    ):
                        self.assertGreaterEqual(
                            len(contract["operand_refs"]), 2
                        )
                    if contract["algorithm"] == "HASH_AND_BYTE_LINEAGE_V1":
                        self.assertGreaterEqual(
                            len(contract["operand_refs"]), 2
                        )
                    if "CARDINALITY" in invariant_id:
                        self.assertEqual(
                            contract["algorithm"],
                            "EXACT_ARRAY_CARDINALITY_COMPARISON_V1",
                        )
                        self.assertEqual(len(contract["operand_refs"]), 2)
                    if contract["algorithm"] == (
                        "ORDERED_NUMERIC_PREDICATE_V1"
                    ):
                        self.assertIn("relation", contract["parameters"])
                        self.assertIn("unit", contract["parameters"])

    def test_validator_rejects_unresolved_invariant_operand(self) -> None:
        self.configure_derived_media_atoms(("ASSET_PLAN",))
        self.compile()
        self.make_candidate_writable()
        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = next(
            item
            for item in manifest["artifact_index"].values()
            if item["artifact_kind"] == "ASSET_PLAN"
        )
        contract = artifact["schema"]["x-invariant-contracts"][
            "ASSET_PROVENANCE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY"
        ]
        contract["operand_refs"][1] = "/missing_schema_field"
        contract["predicate_ast"]["operand_refs"] = list(
            contract["operand_refs"]
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "INVARIANT_OPERAND_REF_UNRESOLVED", self.finding_codes()
        )

    def test_validator_rejects_invariant_operator_semantic_drift(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "NARRATION_SCRIPT",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "ASSET_BINDING_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "LOCAL_RENDER_RECEIPT",
                "MEDIA_ACCEPTANCE_RECEIPT",
                "RESUMABLE_STAGE_RECEIPT",
            )
        )
        self.compile()
        self.make_candidate_writable()
        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        original = json.loads(manifest_path.read_text(encoding="utf-8"))

        mutations = (
            (
                "ASSET_BINDING_RECEIPT",
                "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS",
                "INVARIANT_OPERATOR_ARITY_INVALID",
                lambda contract: contract.update(
                    {"operand_refs": [contract["target_ref"]]}
                ),
            ),
            (
                "MEDIA_ACCEPTANCE_RECEIPT",
                "ABSOLUTE_FINAL_AV_DRIFT_DOES_NOT_EXCEED_ONE_FRAME",
                "INVARIANT_NUMERIC_PARAMETERS_INCOMPLETE",
                lambda contract: contract.update({"parameters": {}}),
            ),
        )
        for artifact_kind, invariant_id, failure_code, mutate in mutations:
            manifest = deepcopy(original)
            artifact = next(
                item
                for item in manifest["artifact_index"].values()
                if item["artifact_kind"] == artifact_kind
            )
            contract = artifact["schema"]["x-invariant-contracts"][
                invariant_id
            ]
            mutate(contract)
            contract["operand_types"] = contract["operand_types"][: len(
                contract["operand_refs"]
            )]
            contract["cardinality"]["operand_count"] = len(
                contract["operand_refs"]
            )
            contract["predicate_ast"]["operand_refs"] = list(
                contract["operand_refs"]
            )
            contract["predicate_ast"]["operand_types"] = list(
                contract["operand_types"]
            )
            contract["predicate_ast"]["cardinality"] = deepcopy(
                contract["cardinality"]
            )
            contract["predicate_ast"]["parameters"] = deepcopy(
                contract["parameters"]
            )
            manifest_path.write_text(
                json.dumps(
                    manifest, ensure_ascii=False, indent=2, sort_keys=True
                )
                + "\n",
                encoding="utf-8",
            )
            with self.subTest(invariant_id=invariant_id):
                self.assertIn(failure_code, self.finding_codes())

        manifest = deepcopy(original)
        artifact = next(
            item
            for item in manifest["artifact_index"].values()
            if item["artifact_kind"] == "ASSET_PLAN"
        )
        contract = artifact["schema"]["x-invariant-contracts"][
            "ASSET_PROVENANCE_REFS_AND_HASHES_HAVE_EQUAL_CARDINALITY"
        ]
        contract["algorithm"] = "HASH_AND_BYTE_LINEAGE_V1"
        contract["predicate_ast"]["algorithm"] = contract["algorithm"]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "INVARIANT_ALGORITHM_FAMILY_MISMATCH", self.finding_codes()
        )

    def test_public_skill_url_interface_has_unlisted_metamorphic_vector(
        self,
    ) -> None:
        self.compile()
        contract = json.loads(
            (
                self.candidate
                / "validation/PUBLIC_SKILL_JOB_INTERFACE.json"
            ).read_text(encoding="utf-8")
        )
        frozen_urls = {
            item["repository_url"]
            for item in contract["frozen_certification_fixtures"]
        }
        vector = contract["metamorphic_acceptance_vector"]
        request_schema = contract["job_request_schema"]

        self.assertNotIn(vector["input"]["skill_url"], frozen_urls)
        self.assertNotIn(
            "const", request_schema["properties"]["skill_url"]
        )
        self.assertNotIn(
            "enum", request_schema["properties"]["skill_url"]
        )
        self.assertEqual(vector["expected"]["input_skill_count"], 1)
        self.assertEqual(vector["expected"]["output_video_count"], 1)
        self.assertEqual(
            vector["expected"]["job_id_derivation"],
            "SHA256_CANONICAL_RESOLVED_JOB_IDENTITY_PREFIX_16",
        )
        self.assertEqual(
            vector["input"]["skill_url"],
            PUBLIC_SKILL_METAMORPHIC_REPOSITORY_URL,
        )
        self.assertEqual(
            vector["input"]["skill_entrypoint_ref"],
            PUBLIC_SKILL_METAMORPHIC_ENTRYPOINT_REF,
        )
        self.assertNotIn("resolved_source", vector)
        resolution = vector["resolution_contract"]
        self.assertEqual(
            resolution["status"], "RUNTIME_RESOLUTION_REQUIRED_NOT_RUN"
        )
        self.assertEqual(
            resolution["resolution_receipt_ref"],
            PUBLIC_SKILL_METAMORPHIC_RESOLUTION_RECEIPT_REF,
        )
        self.assertTrue(resolution["simulated_resolution_values_forbidden"])
        resolution_schema = resolution["resolution_receipt_schema"]
        self.assertEqual(
            resolution_schema["properties"]["resolved_commit_sha"]["pattern"],
            "^[0-9a-f]{40}$",
        )
        self.assertEqual(
            resolution_schema["x-ref-sha256-bindings"],
            [
                {
                    "ref_pointer": "/resolved_tree_ref",
                    "sha256_pointer": "/resolved_tree_sha256",
                },
                {
                    "ref_pointer": "/resolved_skill_entrypoint_ref",
                    "sha256_pointer": "/resolved_skill_entrypoint_sha256",
                },
                {
                    "ref_pointer": "/resolution_command_receipt_ref",
                    "sha256_pointer": "/resolution_command_receipt_sha256",
                },
            ],
        )
        self.assertEqual(
            vector["expected"]["expected_job_id_source"],
            "HASH_VERIFIED_RUNTIME_RESOLUTION_RECEIPT_FIELDS",
        )
        specialization = contract["dynamic_specialization_contract"]
        self.assertEqual(
            specialization["job_identity_derivation_stage"],
            "AFTER_EXACT_SOURCE_RESOLUTION",
        )
        self.assertNotIn(
            "requested_revision", specialization["job_identity_fields"]
        )
        self.assertIn(
            "skill_entrypoint_ref", specialization["job_identity_fields"]
        )
        self.assertTrue(
            vector["expected"]["video_artifact_descriptor_required"]
        )
        case_manifest = json.loads(
            (
                self.candidate / "validation/CASE_EXECUTION_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        invocation = next(
            item
            for item in case_manifest["metamorphic_case_invocations"]
            if item["case_id"] == vector["case_id"]
        )
        self.assertEqual(invocation["case_kind"], "METAMORPHIC")
        self.assertIn(
            invocation["result_ref"],
            case_manifest["expected_case_result_refs"],
        )
        self.assertEqual(
            invocation["executor_command_id"], "LAB-RUN-METAMORPHIC-CASE"
        )
        self.assertEqual(
            invocation["source_resolution_entrypoint"],
            PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT,
        )
        command = next(
            item
            for item in case_manifest["commands"]
            if item["command_id"] == "LAB-RUN-METAMORPHIC-CASE"
        )
        self.assertEqual(
            command["implementation_entrypoint"],
            PUBLIC_SKILL_JOB_PIPELINE_ENTRYPOINT,
        )
        self.assertEqual(
            command["parameter_contract"]["source_resolution_entrypoint"],
            PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT,
        )
        lab_bundle = json.loads(
            (
                self.candidate
                / "project_start_packages/external_lab/task_bundles/"
                "LAB-CLI.task_bundle.json"
            ).read_text(encoding="utf-8")
        )
        lab_contract = lab_bundle["lab_case_execution_contract"]
        self.assertEqual(
            lab_contract["required_source_resolution_entrypoint"],
            PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT,
        )
        self.assertIn(
            "Implement and invoke "
            f"{PUBLIC_SKILL_SOURCE_RESOLUTION_ENTRYPOINT} from "
            "run-metamorphic-case before content analysis.",
            lab_contract["implementation_obligations"],
        )
        self.assertEqual(contract["status"], "DECLARE_ONLY_NOT_RUN")

    def test_personal_local_candidate_omits_release_only_negative_cases(self) -> None:
        self.ir["target"]["start_package_immutability_policy"] = {
            "physical_permission_enforcement": "BEST_EFFORT_PERSONAL_LOCAL",
            "permission_drift_disposition": "NON_BLOCKING_DIAGNOSTIC",
        }
        self.compile()
        negative = json.loads(
            (
                self.candidate / "validation/NEGATIVE_CASES.json"
            ).read_text(encoding="utf-8")
        )
        cases = {case["case_id"]: case for case in negative["cases"]}
        self.assertIn("NEG-HF28-CODEX-SELF-REPORT", cases)
        self.assertNotIn("NEG-HF28-ATTESTATION-REPLAY", cases)
        self.assertNotIn("NEG-HF28-THREE-PROJECT-ORDER", cases)
        self.assertEqual(
            cases["NEG-HF28-CODEX-SELF-REPORT"]["assurance_profile"],
            "LOCAL_EXEC_UNTRUSTED_INPUT",
        )

    def test_validator_does_not_reuse_producer_registry_builders(self) -> None:
        validator_path = (
            REPOSITORY_ROOT / "src/harness_foundry_factory/validator.py"
        )
        tree = ast.parse(validator_path.read_text(encoding="utf-8"))
        forbidden = {"oracle_evaluator_registry", "repository_job_bindings"}
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and (node.module or "").endswith("semantic_contracts")
            for alias in node.names
        }
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            forbidden & imported,
            "Validator must not import Producer registry builders",
        )
        self.assertFalse(
            forbidden & called,
            "Validator must independently validate persisted registry bytes",
        )

    def test_validator_rejects_public_resolver_reachability_drift(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/CASE_EXECUTION_MANIFEST.json"
        original = json.loads(path.read_text(encoding="utf-8"))

        for replacement, failure_code in (
            (None, "PUBLIC_SKILL_SOURCE_RESOLVER_UNREACHABLE"),
            (
                "external_lab.sources:wrong_resolver",
                "PUBLIC_SKILL_SOURCE_RESOLVER_BINDING_MISMATCH",
            ),
        ):
            manifest = deepcopy(original)
            command = next(
                item
                for item in manifest["commands"]
                if item["command_id"] == "LAB-RUN-METAMORPHIC-CASE"
            )
            if replacement is None:
                command["job_pipeline_contract"].pop("source_resolution_entrypoint")
            else:
                command["job_pipeline_contract"]["source_resolution_entrypoint"] = replacement
            command["command_sha256"] = hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in command.items()
                        if key != "command_sha256"
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            manifest["manifest_sha256"] = hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "manifest_sha256"
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            path.write_text(
                json.dumps(
                    manifest, ensure_ascii=False, indent=2, sort_keys=True
                )
                + "\n",
                encoding="utf-8",
            )
            with self.subTest(replacement=replacement):
                self.assertIn(failure_code, self.finding_codes())

    def test_explicit_semantics_requires_lab_cli_resolver_bundle(self) -> None:
        self.compile()
        self.make_candidate_writable()
        (
            self.candidate
            / "project_start_packages/external_lab/task_bundles/"
            "LAB-CLI.task_bundle.json"
        ).unlink()

        codes = self.finding_codes()
        self.assertIn("JSON_READ_FAILED", codes)
        self.assertIn("PUBLIC_SKILL_SOURCE_RESOLVER_UNREACHABLE", codes)

    def test_validator_rejects_incomplete_invariant_contract_set(self) -> None:
        self.configure_derived_media_atoms(("NARRATION_SCRIPT",))
        self.compile()
        self.make_candidate_writable()
        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        narration = next(
            artifact
            for artifact in manifest["artifact_index"].values()
            if artifact["artifact_kind"] == "NARRATION_SCRIPT"
        )
        narration["schema"]["x-invariant-contracts"].pop(
            "NARRATION_BUDGET_ESTIMATE_MATCHES_CANONICAL_SENTENCE_ARRAY_AND_METHOD"
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "ARTIFACT_INVARIANT_CONTRACT_INCOMPLETE",
            self.finding_codes(),
        )

    def test_validator_rejects_quantifier_selector_drift(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "NARRATION_SCRIPT",
            )
        )
        self.compile()
        self.make_candidate_writable()
        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        quantified = sorted(
            (
                artifact_id,
                invariant_id,
            )
            for artifact_id, artifact in original["artifact_index"].items()
            for invariant_id in artifact["schema"].get(
                "x-invariant-contracts", {}
            )
            if invariant_id.startswith(("EVERY_", "ALL_", "EACH_"))
        )
        self.assertGreaterEqual(len(quantified), 3)
        for position in (0, len(quantified) // 2, len(quantified) - 1):
            manifest = deepcopy(original)
            artifact_id, invariant_id = quantified[position]
            contract = manifest["artifact_index"][artifact_id]["schema"][
                "x-invariant-contracts"
            ][invariant_id]
            contract["subject_selector"] = contract["target_ref"]
            manifest_path.write_text(
                json.dumps(
                    manifest, ensure_ascii=False, indent=2, sort_keys=True
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertIn(
                "INVARIANT_QUANTIFIER_CONTRACT_INCOMPLETE",
                self.finding_codes(),
            )

    def test_validator_rejects_authorized_branch_precondition_drift(self) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
            )
        )
        self.compile()
        self.make_candidate_writable()
        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        gate = next(
            artifact
            for artifact in manifest["artifact_index"].values()
            if artifact["artifact_kind"] == "BEFORE_AFTER_DEMO_CONTRACT"
        )
        contract = gate["schema"]["x-invariant-contracts"][
            "AUTHORIZED_TARGET_SKILL_RUN_REQUIRES_CURRENT_EXACT_AUTHORIZATION_AND_RECEIPT"
        ]
        contract["branch_precondition"] = "ANY_JSON_SCHEMA_VALID_BRANCH"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "INVARIANT_BRANCH_PRECONDITION_INCOMPATIBLE",
            self.finding_codes(),
        )

    def test_validator_rejects_denied_branch_selector_rebinding(self) -> None:
        self.configure_derived_media_atoms(
            ("TARGET_SKILL_EXECUTION_GATE_RECEIPT",)
        )
        self.compile()
        self.make_candidate_writable()
        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        gate = next(
            artifact
            for artifact in manifest["artifact_index"].values()
            if artifact["artifact_kind"]
            == "TARGET_SKILL_EXECUTION_GATE_RECEIPT"
        )
        contract = gate["schema"]["x-invariant-contracts"][
            "DENIED_TARGET_SKILL_GATE_HAS_NO_AUTHORIZATION_OR_SIDE_EFFECT_ATTEMPT"
        ]
        wrong_selector = {
            "mode": "REQUIRE_DISCRIMINATOR_CONST",
            "discriminator_ref": "/status",
            "const": "AUTHORIZED_EXECUTION_RECEIPT_VALID",
        }
        contract["branch_precondition"] = wrong_selector["const"]
        contract["branch_selector"] = wrong_selector
        contract["predicate_ast"]["branch_precondition"] = wrong_selector[
            "const"
        ]
        contract["predicate_ast"]["branch_selector"] = wrong_selector
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "INVARIANT_BRANCH_PRECONDITION_INCOMPATIBLE",
            self.finding_codes(),
        )

    def test_validator_rejects_illustration_branch_selector_rebinding(
        self,
    ) -> None:
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "BEFORE_AFTER_DEMO_CONTRACT",
            )
        )
        self.compile()
        self.make_candidate_writable()
        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        demo = next(
            artifact
            for artifact in manifest["artifact_index"].values()
            if artifact["artifact_kind"] == "BEFORE_AFTER_DEMO_CONTRACT"
        )
        contract = demo["schema"]["x-invariant-contracts"][
            "ILLUSTRATION_IS_EXPLICITLY_LABELED_AND_NOT_ACTUAL_SKILL_OUTPUT"
        ]
        wrong_selector = {
            "mode": "REQUIRE_DISCRIMINATOR_CONST",
            "discriminator_ref": "/provenance_state",
            "const": "OBSERVED_REPO_FIXTURE",
        }
        contract["branch_precondition"] = wrong_selector["const"]
        contract["branch_selector"] = wrong_selector
        contract["predicate_ast"]["branch_precondition"] = wrong_selector[
            "const"
        ]
        contract["predicate_ast"]["branch_selector"] = wrong_selector
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "INVARIANT_BRANCH_PRECONDITION_INCOMPATIBLE",
            self.finding_codes(),
        )

    def test_validator_rejects_public_skill_url_fixture_lock_in(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/PUBLIC_SKILL_JOB_INTERFACE.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["job_request_schema"]["properties"]["skill_url"] = {
            "const": "https://github.com/example/fixed-only-skill"
        }
        path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "PUBLIC_SKILL_JOB_INTERFACE_INVALID",
            self.finding_codes(),
        )

    def test_validator_rejects_simulated_public_source_resolution(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/PUBLIC_SKILL_JOB_INTERFACE.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["metamorphic_acceptance_vector"]["resolved_source"] = {
            "normalized_skill_url": PUBLIC_SKILL_METAMORPHIC_REPOSITORY_URL,
            "resolved_commit_sha": "1" * 40,
            "resolved_git_tree_oid": "2" * 40,
            "resolved_tree_sha256": "3" * 64,
            "resolution_method": "SIMULATED_METAMORPHIC_FIXTURE",
        }
        contract["interface_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in contract.items()
                    if key != "interface_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "PUBLIC_SKILL_JOB_INTERFACE_INVALID",
            self.finding_codes(),
        )

    def test_validator_rejects_mutable_public_job_identity(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/PUBLIC_SKILL_JOB_INTERFACE.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        specialization = contract["dynamic_specialization_contract"]
        specialization["job_id_derivation"] = (
            "SHA256_CANONICAL_JOB_REQUEST_PREFIX_16"
        )
        specialization["job_identity_derivation_stage"] = "BEFORE_SOURCE_RESOLUTION"
        specialization["job_identity_fields"] = [
            "skill_url",
            "requested_revision",
        ]
        contract["metamorphic_acceptance_vector"]["expected"][
            "job_id_derivation"
        ] = specialization["job_id_derivation"]
        contract["interface_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in contract.items()
                    if key != "interface_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "PUBLIC_SKILL_JOB_IDENTITY_NOT_IMMUTABLY_RESOLVED",
            self.finding_codes(),
        )

    def test_validator_rejects_public_case_closure_drift(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/CASE_EXECUTION_MANIFEST.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["metamorphic_case_invocations"] = []
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in manifest.items()
                    if key != "manifest_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "PUBLIC_SKILL_JOB_CASE_CLOSURE_INCOMPLETE",
            self.finding_codes(),
        )

    def test_validator_rejects_public_skill_entrypoint_identity_drift(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/PUBLIC_SKILL_JOB_INTERFACE.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        contract["metamorphic_acceptance_vector"]["input"][
            "skill_entrypoint_ref"
        ] = "README.md"
        contract["interface_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in contract.items()
                    if key != "interface_sha256"
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "PUBLIC_SKILL_JOB_INTERFACE_INVALID", self.finding_codes()
        )

    def test_validator_rejects_public_video_descriptor_removal(self) -> None:
        self.compile()
        self.make_candidate_writable()
        manifest = json.loads(
            (
                self.candidate / "validation/CASE_EXECUTION_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        invocation = manifest["metamorphic_case_invocations"][0]
        schema_path = self.candidate / invocation[
            "result_schema_ref"
        ].removeprefix("harness-resource://candidate/")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["properties"]["artifacts"]["required"].remove("video")
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "PUBLIC_SKILL_JOB_CASE_CLOSURE_INCOMPLETE",
            self.finding_codes(),
        )

    def test_validator_rejects_case_partition_aggregation_drift(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/ACCEPTANCE_CASES.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["cases"][0].pop("aggregation_executor_command_id")
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "CASE_PARTITION_AGGREGATION_CONTRACT_INCOMPLETE",
            self.finding_codes(),
        )

    def test_validator_rejects_case_result_ref_sha256_binding_drift(
        self,
    ) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/schemas/CASE_RESULT.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["x-ref-sha256-bindings"][0]["sha256_pointer"] = (
            "/fixture_sha256"
        )
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn("CASE_EXECUTION_MANIFEST_INVALID", self.finding_codes())

    def test_validator_rejects_aggregation_receipt_byte_lineage_drift(
        self,
    ) -> None:
        self.compile()
        self.make_candidate_writable()
        acceptance_path = self.candidate / "validation/ACCEPTANCE_CASES.json"
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        case = acceptance["cases"][0]
        schema_path = self.candidate / case[
            "aggregation_receipt_schema_ref"
        ].removeprefix("harness-resource://candidate/")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["x-ref-sha256-bindings"].pop()
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "CASE_PARTITION_AGGREGATION_CONTRACT_INCOMPLETE",
            self.finding_codes(),
        )

    def test_validation_report_has_check_specific_evidence(self) -> None:
        self.compile()
        report = json.loads(
            (
                self.candidate
                / "validation/START_PACKAGE_VALIDATION_REPORT.json"
            ).read_text(encoding="utf-8")
        )
        checks = {
            item["check_id"]: item for item in report["checks"]
        }
        executable = set(
            checks["EXECUTABLE_ACCEPTANCE_AND_ORACLE_CONTRACTS"][
                "evidence_refs"
            ]
        )
        identity = set(
            checks["IDENTITY_REFERENCES_AND_HASHES"]["evidence_refs"]
        )

        self.assertTrue(
            {
                "validation/PUBLIC_SKILL_JOB_INTERFACE.json",
                "validation/CASE_EXECUTION_MANIFEST.json",
                "validation/ORACLE_EVALUATOR_REGISTRY.json",
                "validation/schemas/CASE_RESULT.schema.json",
            }.issubset(executable)
        )
        self.assertNotEqual(executable, identity)

    def test_validator_rejects_generic_validation_report_evidence(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = (
            self.candidate
            / "validation/START_PACKAGE_VALIDATION_REPORT.json"
        )
        report = json.loads(path.read_text(encoding="utf-8"))
        generic = [
            "PACKAGE_MANIFEST.json",
            "START_CONTEXT.json",
            "ENGINEERING_PROJECT_DAG.json",
        ]
        for check in report["checks"]:
            check["evidence_refs"] = list(generic)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "VALIDATION_REPORT_CHECK_EVIDENCE_INCOMPLETE",
            self.finding_codes(),
        )

    def test_lab_case_writer_owns_partitioned_lineage_and_graph_evidence(
        self,
    ) -> None:
        for index in range(1, 3):
            source = deepcopy(self.ir["sources"][0])
            source.update(
                {
                    "source_id": f"SRC-LAB-LINEAGE-{index}",
                    "repository_url": (
                        f"https://github.com/example/lab-lineage-{index}"
                    ),
                    "revision": "main",
                    "commit_sha": str(index) * 40,
                    "git_tree_oid": str(index + 3) * 40,
                    "tree_sha256": source["sha256"],
                    "license_spdx": "MIT",
                    "scope": "Lab lineage regression fixture",
                }
            )
            self.ir["sources"].append(source)
        self.ir["atoms"] = [
            {
                "atom_id": "ATOM-MEDIA-LINEAGE",
                "text_or_lossless_paraphrase": (
                    "Bind final video bytes to terminal media acceptance."
                ),
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "MEDIA_ACCEPTANCE_RECEIPT",
            },
            {
                "atom_id": "ATOM-LAB-LINEAGE",
                "text_or_lossless_paraphrase": (
                    "Certify every Case result and referenced video byte set."
                ),
                "owner": "EXTERNAL_CONFORMANCE_LAB",
                "verification_mode": "INDEPENDENT_FIXTURE_ACCEPTANCE",
            },
            {
                "atom_id": "ATOM-AUTHORING-BOUNDARY",
                "text_or_lossless_paraphrase": (
                    "Reject any authoring-time Workpack, Driver, Harness, model, or media execution."
                ),
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "AUTHORING_STOP_RECEIPT",
            },
        ]
        atom_ids = [item["atom_id"] for item in self.ir["atoms"]]
        for case in (*self.ir["acceptance_cases"], *self.ir["negative_cases"]):
            case["atom_ids"] = list(atom_ids)
        self.ir["coverage_edges"] = normalize_ir_coverage(self.ir)[
            "coverage_edges"
        ]
        self.ir["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        self.ir["target"]["artifact_schema_catalog"] = {
            "ATOM-MEDIA-LINEAGE": {
                "artifact_kind": "MEDIA_ACCEPTANCE_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "PASS"}},
                },
            },
            "ATOM-LAB-LINEAGE": {
                "artifact_kind": "FIXTURE_PLAN",
                "schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "PASS"}},
                },
            },
            "ATOM-AUTHORING-BOUNDARY": {
                "artifact_kind": "AUTHORING_STOP_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "PASS"}},
                },
            },
        }

        self.compile()

        case_manifest = json.loads(
            (
                self.candidate / "validation/CASE_EXECUTION_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        result_root = "harness-resource://execution/evidence/cases"
        self.assertEqual(case_manifest["owner_workpack_id"], "LAB-CERTIFICATION")
        self.assertEqual(case_manifest["result_root_ref"], result_root)
        self.assertEqual(
            len(case_manifest["expected_case_result_refs"]),
            len(set(case_manifest["expected_case_result_refs"])),
        )
        self.assertEqual(
            {item["command_id"] for item in case_manifest["commands"]},
            {
                "LAB-RUN-ACCEPTANCE-CASE",
                "LAB-RUN-NEGATIVE-CASE",
                "LAB-RUN-REGISTRY-CASE",
                "LAB-RUN-CASE-PARTITION",
                "LAB-AGGREGATE-CASE-PARTITIONS",
                "LAB-RUN-METAMORPHIC-CASE",
                "LAB-EVALUATE-CASE-ORACLE",
            },
        )

        acceptance = json.loads(
            (
                self.candidate / "validation/ACCEPTANCE_CASES.json"
            ).read_text(encoding="utf-8")
        )
        acceptance_case = acceptance["cases"][0]
        self.assertTrue(acceptance_case["job_read_partitions"])
        self.assertEqual(
            len(acceptance_case["partition_executor_argvs"]),
            len(acceptance_case["job_read_partitions"]),
        )
        self.assertEqual(
            acceptance_case["aggregation_executor_command_id"],
            "LAB-AGGREGATE-CASE-PARTITIONS",
        )
        result_schema = json.loads(
            (
                self.candidate
                / acceptance_case["result_schema_ref"].removeprefix(
                    "harness-resource://candidate/"
                )
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            {
                "job_partition_results",
                "job_partition_manifest_sha256",
                "aggregation_receipt_ref",
                "aggregation_receipt_sha256",
            }.issubset(result_schema["required"])
        )
        partition_results = result_schema["properties"][
            "job_partition_results"
        ]
        self.assertEqual(
            partition_results["minItems"],
            len(acceptance_case["job_read_partitions"]),
        )
        self.assertEqual(
            partition_results["maxItems"],
            len(acceptance_case["job_read_partitions"]),
        )

        certification = json.loads(
            (
                self.candidate
                / "project_start_packages/external_lab/commands/"
                "LAB-CERTIFICATION.commands.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            certification["workpack_auxiliary_write_roots"], [result_root]
        )
        runner = next(
            item
            for item in certification["commands"]
            if item["command_id"] == "LAB-RUN-ACCEPTANCE-CASE"
        )
        self.assertFalse(runner["job_artifact_read_scopes"])
        self.assertIsNone(runner["job_artifact_lease_contract"])

        partition_runner = next(
            item
            for item in certification["commands"]
            if item["command_id"] == "LAB-RUN-CASE-PARTITION"
        )
        self.assertTrue(partition_runner["job_artifact_read_scopes"])
        self.assertEqual(
            partition_runner["job_artifact_lease_contract"][
                "selection_cardinality"
            ],
            "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_CASE_PARTITION",
        )
        aggregator = next(
            item
            for item in certification["commands"]
            if item["command_id"] == "LAB-AGGREGATE-CASE-PARTITIONS"
        )
        self.assertFalse(aggregator["job_artifact_read_scopes"])

        manifest_path = (
            self.candidate
            / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        media_ids = {
            artifact_id
            for artifact_id, artifact in manifest["artifact_index"].items()
            if artifact["artifact_kind"] == "MEDIA_ACCEPTANCE_RECEIPT"
        }
        fixture_id, fixture = next(
            (artifact_id, artifact)
            for artifact_id, artifact in manifest["artifact_index"].items()
            if artifact["artifact_kind"] == "FIXTURE_ACCEPTANCE_RECEIPT"
        )
        self.assertEqual(
            fixture["depends_on_evidence_refs"],
            case_manifest["expected_case_result_refs"],
        )
        self.assertTrue(media_ids.issubset(fixture["depends_on_artifact_ids"]))
        expected_lab_dependency_ids = {
            artifact_id
            for artifact_id in manifest["artifact_index"]
            if artifact_id != fixture_id
        }
        self.assertEqual(
            set(fixture["depends_on_artifact_ids"]),
            expected_lab_dependency_ids,
        )
        expected_job_roots: dict[str, set[str]] = {}
        expected_shared_roots: set[str] = set()
        for artifact_id in fixture["depends_on_artifact_ids"]:
            artifact = manifest["artifact_index"][artifact_id]
            artifact_root = artifact["artifact_ref"].rsplit("/", 1)[0]
            job_id = artifact.get("job_id")
            if job_id:
                expected_job_roots.setdefault(job_id, set()).add(artifact_root)
            else:
                expected_shared_roots.add(artifact_root)
        actual_job_roots = {
            scope["job_id"]: set(scope["allowed_read_roots"])
            for scope in partition_runner["job_artifact_read_scopes"]
        }
        self.assertEqual(actual_job_roots, expected_job_roots)
        self.assertTrue(
            expected_shared_roots.issubset(set(runner["allowed_read_roots"]))
        )
        authoring_stop_root = next(
            artifact["artifact_ref"].rsplit("/", 1)[0]
            for artifact in manifest["artifact_index"].values()
            if artifact["artifact_kind"] == "AUTHORING_STOP_RECEIPT"
        )
        self.assertIn(authoring_stop_root, runner["allowed_read_roots"])
        self.assertEqual(
            fixture["case_evidence_ownership"],
            {
                "writer_workpack_id": "LAB-CERTIFICATION",
                "result_root_ref": result_root,
                "writer_cardinality": "EXACTLY_ONE_WORKPACK",
                "consumer_requires_hash_bound_bytes": True,
            },
        )
        graph_edges = {
            (
                item["from_node_id"],
                item["to_node_id"],
                item["edge_kind"],
            )
            for item in manifest["composite_dependency_graph"]["edges"]
        }
        for evidence_ref in fixture["depends_on_evidence_refs"]:
            self.assertIn(
                (
                    f"EVIDENCE:{evidence_ref}",
                    f"ARTIFACT:{fixture_id}",
                    "EXECUTION_EVIDENCE_REQUIRED_BY_ARTIFACT",
                ),
                graph_edges,
            )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

        self.make_candidate_writable()
        frozen_path = (
            self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        )
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        frozen_fixture = next(
            artifact
            for atom in frozen["atoms"]
            for obligation in atom["production_contract"][
                "workpack_obligations"
            ]
            for artifact in obligation["artifact_obligations"]
            if artifact["artifact_id"] == fixture_id
        )
        frozen_fixture["depends_on_evidence_refs"] = []
        frozen_path.write_text(
            json.dumps(frozen, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "FIXTURE_ACCEPTANCE_LINEAGE_CONTRACT_INCOMPLETE",
            self.finding_codes(),
        )

    def test_repository_business_artifacts_are_isolated_by_fixed_job(self) -> None:
        value = deepcopy(self.ir)
        value["sources"] = [
            {
                "source_id": f"SRC-REPOSITORY-{index}",
                "repository_url": f"https://github.com/example/skill-{index}",
                "revision": "main",
                "commit_sha": str(index) * 40,
                "git_tree_oid": str(index + 3) * 40,
                "tree_sha256": str(index + 6) * 64,
                "sha256": str(index + 6) * 64,
            }
            for index in range(1, 4)
        ]
        value["atoms"] = [
            {
                "atom_id": "ATOM-FUNCTION",
                "text_or_lossless_paraphrase": "Bind every source claim to its own job.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "FUNCTION_SCENARIO_EFFECT_MATRIX",
            },
            {
                "atom_id": "ATOM-FIXTURES",
                "text_or_lossless_paraphrase": "Accept exactly three isolated fixtures.",
                "owner": "EXTERNAL_CONFORMANCE_LAB",
                "verification_mode": "INDEPENDENT_FIXTURE_ACCEPTANCE",
            },
        ]
        value["acceptance_cases"] = [
            {
                "case_id": f"AC-VIDEO-{index}",
                "atom_ids": ["ATOM-FIXTURES"],
                "description": f"Acceptance case {index}.",
                "evidence_type": "FIXTURE_ACCEPTANCE_RECEIPT",
            }
            for index in range(1, 7)
        ]
        value["negative_cases"] = [
            {
                "case_id": f"NEG-VIDEO-{index}",
                "atom_ids": ["ATOM-FIXTURES"],
                "description": f"Negative case {index}.",
                "expected_failure": f"VIDEO_NEGATIVE_{index}_REJECTED",
            }
            for index in range(1, 7)
        ]
        value["coverage_edges"] = normalize_ir_coverage(value)["coverage_edges"]
        value["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        value["target"]["artifact_schema_catalog"] = {
            "ATOM-FUNCTION": {
                "artifact_kind": "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "schema": {
                    "type": "object",
                    "required": ["claim_id", "function", "trigger_scenario", "effect"],
                    "properties": {
                        "claim_id": {"type": "string"},
                        "function": {"type": "string"},
                        "trigger_scenario": {"type": "string"},
                        "effect": {"type": "string"},
                    },
                },
            },
            "ATOM-FIXTURES": {
                "artifact_kind": "FIXTURE_PLAN",
                "schema": {
                    "type": "object",
                    "required": ["fixtures", "isolation_policy"],
                    "properties": {
                        "fixtures": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "required": [
                                    "fixture_id",
                                    "repository_url",
                                    "commit_sha",
                                    "expected_function",
                                    "expected_scenario",
                                    "expected_effect",
                                    "demo_contract_ref",
                                ],
                            },
                        },
                        "isolation_policy": {
                            "const": "ONE_REPOSITORY_ONE_JOB_ONE_VIDEO"
                        },
                    },
                },
            },
        }

        compiled = compile_declared_production_contracts(value)
        artifacts = [
            artifact
            for atom in compiled["atoms"]
            for obligation in atom["production_contract"]["workpack_obligations"]
            for artifact in obligation["artifact_obligations"]
        ]
        function_artifacts = [
            item
            for item in artifacts
            if item["artifact_kind"] == "FUNCTION_SCENARIO_EFFECT_MATRIX"
        ]
        self.assertEqual(len(function_artifacts), 3)
        self.assertEqual(len({item["artifact_ref"] for item in function_artifacts}), 3)
        for artifact in function_artifacts:
            self.assertIn(artifact["job_id"], artifact["artifact_ref"])
            self.assertEqual(
                artifact["schema"]["properties"]["job_id"]["const"],
                artifact["job_id"],
            )
            self.assertEqual(
                artifact["schema"]["properties"]["source_id"]["const"],
                artifact["source_id"],
            )
            self.assertIn("claims", artifact["schema"]["required"])
        manifest = build_artifact_obligation_manifest(
            value,
            target_id="TEST-TARGET",
            program_id="TEST-PROGRAM",
            requirement_ir_sha256="a" * 64,
            atom_catalog_sha256="b" * 64,
            coverage_matrix_sha256="c" * 64,
        )
        self.assertIsNotNone(manifest)
        manifest_index = manifest["artifact_index"]
        for artifact in function_artifacts:
            indexed = manifest_index[artifact["artifact_id"]]
            self.assertEqual(indexed["job_id"], artifact["job_id"])
            self.assertEqual(indexed["source_id"], artifact["source_id"])
        fixture_artifact = next(
            item
            for item in artifacts
            if item["artifact_kind"] == "FIXTURE_ACCEPTANCE_RECEIPT"
        )
        fixture_items = fixture_artifact["schema"]["properties"]["fixture_results"]
        self.assertTrue(fixture_items["uniqueItems"])
        acceptance_count = len(value["acceptance_cases"])
        negative_count = len(
            negative_case_specs_with_mandatory_controls(value)
        )
        acceptance_results = fixture_artifact["schema"]["properties"][
            "acceptance_case_results"
        ]
        negative_results = fixture_artifact["schema"]["properties"][
            "negative_case_results"
        ]
        invariant_results = fixture_artifact["schema"]["properties"][
            "invariant_negative_case_results"
        ]
        schema_native_results = fixture_artifact["schema"]["properties"][
            "schema_native_negative_case_results"
        ]
        self.assertEqual(acceptance_results["minItems"], acceptance_count)
        self.assertEqual(acceptance_results["maxItems"], acceptance_count)
        self.assertEqual(negative_results["minItems"], negative_count)
        self.assertEqual(negative_results["maxItems"], negative_count)
        self.assertIn(
            "invariant_negative_case_results",
            fixture_artifact["schema"]["required"],
        )
        self.assertIn(
            "schema_native_negative_case_results",
            fixture_artifact["schema"]["required"],
        )
        invariant_item = invariant_results["items"]
        self.assertTrue(
            {
                "case_id",
                "artifact_kind",
                "evaluator_id",
                "invariant_id",
                "schema_instance_results",
            }.issubset(invariant_item["required"])
        )
        schema_result = invariant_item["properties"][
            "schema_instance_results"
        ]["items"]
        self.assertTrue(
            {
                "schema_sha256",
                "result_ref",
                "result_sha256",
                "base_schema_pass",
                "base_oracle_pass",
                "mutated_schema_pass",
                "observed_failure_code",
                "side_effects_started",
                "status",
            }.issubset(schema_result["required"])
        )
        schema_native_item = schema_native_results["items"]
        self.assertTrue(
            {
                "case_id",
                "artifact_kind",
                "constraint_id",
                "schema_instance_results",
            }.issubset(schema_native_item["required"])
        )
        schema_native_result = schema_native_item["properties"][
            "schema_instance_results"
        ]["items"]
        self.assertTrue(
            {
                "base_schema_pass",
                "mutated_schema_pass",
                "oracle_started",
                "side_effects_started",
            }.issubset(schema_native_result["required"])
        )
        self.assertEqual(acceptance_count, 6)
        self.assertEqual(negative_count, 28)
        self.assertEqual(
            len(fixture_artifact["schema"]["allOf"]),
            3 + acceptance_count + negative_count,
        )
        semantic_fields = {
            "expected_function",
            "expected_scenario",
            "expected_effect",
            "demo_contract_ref",
        }
        self.assertTrue(
            semantic_fields.issubset(
                fixture_items["items"]["properties"]
            )
        )

    def test_media_contract_closes_script_timeline_and_render_observation(self) -> None:
        value = deepcopy(self.ir)

        def atom(atom_id: str, kind: str) -> dict:
            return {
                "atom_id": atom_id,
                "text_or_lossless_paraphrase": f"Produce {kind}.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": kind,
            }

        kinds = (
            "SOURCE_FREEZE_RECEIPT",
            "FUNCTION_SCENARIO_EFFECT_MATRIX",
            "ASSET_PLAN",
            "BEFORE_AFTER_DEMO_CONTRACT",
            "LOCAL_TTS_RECEIPT",
            "AUDIO_ALIGNMENT_RECEIPT",
            "OBJECT_MOTION_IR",
            "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
            "RESUMABLE_STAGE_RECEIPT",
            "LOCAL_RENDER_RECEIPT",
            "MEDIA_ACCEPTANCE_RECEIPT",
        )
        value["atoms"] = [atom(f"ATOM-{index}", kind) for index, kind in enumerate(kinds)]
        value["coverage_edges"] = normalize_ir_coverage(value)["coverage_edges"]
        value["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        architecture_failure_returns = [
            "INSUFFICIENT_SOURCE_EVIDENCE",
            "FUNCTION_EFFECT_UNSUPPORTED",
            "NARRATION_BUDGET_UNSATISFIED",
            "LOCAL_TTS_UNAVAILABLE",
            "TTS_DURATION_DRIFT",
            "FORCED_ALIGNMENT_FAILED",
            "ASSET_ROUTE_UNRESOLVED",
            "CODEX_IMAGE_GENERATION_AUTHORIZATION_REQUIRED",
            "TARGET_SKILL_EXECUTION_DISABLED",
            "TARGET_SKILL_EXECUTION_AUTHORIZATION_REQUIRED",
            "MOTION_OBJECT_CONTRACT_INCOMPLETE",
            "MOTION_SYNC_TOLERANCE_EXCEEDED",
            "DISPLAY_COPY_REWRITE_REQUIRED",
            "RENDER_FAILED",
            "AUDIO_VIDEO_DRIFT",
            "CONTENT_EVIDENCE_MISMATCH",
            "TECHNICAL_ACCEPTANCE_FAILED",
        ]
        value["target"]["architecture_input"] = {
            "failure_returns": architecture_failure_returns,
        }
        value["target"]["artifact_schema_catalog"] = {
            item["atom_id"]: {
                "artifact_kind": item["verification_mode"],
                "schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "PASS"}},
                },
            }
            for item in value["atoms"]
        }

        compiled = compile_declared_production_contracts(value)
        all_artifacts = [
            artifact
            for item in compiled["atoms"]
            for obligation in item["production_contract"]["workpack_obligations"]
            for artifact in obligation["artifact_obligations"]
        ]
        artifacts = {
            artifact["artifact_kind"]: artifact
            for artifact in all_artifacts
        }
        routed_failure_returns = {
            route["error_code"]
            for artifact in all_artifacts
            for route in artifact["failure_returns"]
        }
        self.assertTrue(
            set(architecture_failure_returns).issubset(routed_failure_returns)
        )
        self.assertTrue(
            all(
                artifact["failure_return"] == artifact["failure_returns"][0]
                for artifact in all_artifacts
            )
        )
        source = artifacts["SOURCE_FREEZE_RECEIPT"]["schema"]
        self.assertGreater(len(source["x-invariants"]), 0)
        self.assertTrue(
            {
                "git_tree_oid",
                "frozen_file_refs",
                "frozen_file_sha256s",
                "claim_bindings",
                "source_manifest_ref",
                "source_manifest_sha256",
                "license_evidence_ref",
                "license_evidence_sha256",
            }.issubset(source["required"])
        )
        self.assertIn("NARRATION_SCRIPT", artifacts)
        narration = artifacts["NARRATION_SCRIPT"]["schema"]
        self.assertTrue(
            {
                "narration_budget_verified",
                "narration_budget_estimated_seconds",
                "narration_budget_method",
                "narration_budget_receipt_ref",
                "narration_budget_receipt_sha256",
                "duration_repair_count",
                "playback_speed",
                "truncation_applied",
            }.issubset(narration["required"])
        )
        self.assertEqual(
            narration["properties"]["narration_budget_verified"]["const"],
            True,
        )
        self.assertEqual(
            narration["properties"]["duration_repair_count"]["maximum"],
            2,
        )
        self.assertEqual(
            narration["properties"]["playback_speed"]["const"],
            1.0,
        )
        self.assertEqual(
            narration["properties"]["truncation_applied"]["const"],
            False,
        )
        self.assertIn(
            "NARRATION_BUDGET_RECEIPT_SHA256_MATCHES_REFERENCED_BYTES",
            narration["x-invariants"],
        )
        self.assertIn(
            "NARRATION_BUDGET_ESTIMATE_MATCHES_CANONICAL_SENTENCE_ARRAY_AND_METHOD",
            narration["x-invariants"],
        )
        narration_sentence = artifacts["NARRATION_SCRIPT"]["schema"][
            "properties"
        ]["sentences"]["items"]
        self.assertIn("visual_intent_id", narration_sentence["required"])
        tts_required = artifacts["LOCAL_TTS_RECEIPT"]["schema"]["required"]
        self.assertTrue(
            {
                "narration_script_ref",
                "narration_script_sha256",
                "transcript_ref",
                "transcript_sha256",
                "claim_coverage_sha256",
                "model_artifact_ref",
                "provider_implementation_ref",
                "provider_implementation_sha256",
                "provider_receipt_sha256",
                "runtime_environment_ref",
                "runtime_environment_sha256",
                "license_spdx",
                "license_evidence_ref",
                "license_evidence_sha256",
                "execution_mode",
                "network_accessed",
                "voice_cloned",
            }.issubset(tts_required)
        )
        self.assertIn(
            "AUDIO_SHA256_MATCHES_REFERENCED_AUDIO_BYTES",
            artifacts["LOCAL_TTS_RECEIPT"]["schema"]["x-invariants"],
        )
        motion = artifacts["OBJECT_MOTION_IR"]["schema"]
        self.assertIn("shots", motion["required"])
        self.assertTrue(
            {
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "narration_script_ref",
                "narration_script_sha256",
                "asset_plan_ref",
                "asset_plan_sha256",
                "claim_matrix_ref",
                "claim_matrix_sha256",
            }.issubset(motion["required"])
        )
        self.assertNotIn("shot_id", motion["properties"])
        self.assertEqual(motion["properties"]["duration_seconds"]["minimum"], 175)
        self.assertEqual(motion["properties"]["duration_seconds"]["maximum"], 185)
        self.assertIn("FULL_TIMELINE_CONTIGUOUS_NO_GAPS_OR_OVERLAPS", motion["x-invariants"])
        self.assertIn("motion_curve_ids", motion["required"])
        motion_object = motion["properties"]["shots"]["items"][
            "properties"
        ]["objects"]["items"]
        self.assertTrue(
            {
                "asset_id",
                "sentence_ids",
                "claim_ids",
                "visual_intent_id",
                "audio_anchor_id",
            }.issubset(motion_object["required"])
        )
        segments = motion["properties"]["shots"]["items"]["properties"][
            "objects"
        ]["items"]["properties"]["motion_segments"]
        self.assertEqual(segments["minItems"], 3)
        self.assertEqual(segments["maxItems"], 3)
        curve = segments["items"]
        self.assertEqual(
            curve["properties"]["kind"]["enum"],
            ["TRANSLATE", "SCALE", "ROTATE", "OPACITY", "COMPOSITE"],
        )
        self.assertTrue(
            {
                "segment_id",
                "curve_id",
                "phase",
                "start_seconds",
                "end_seconds",
                "from_state",
                "to_state",
            }.issubset(curve["required"])
        )
        self.assertEqual(
            curve["properties"]["phase"]["enum"],
            ["ENTER", "HOLD", "EXIT"],
        )
        self.assertIn(
            "ENTER_HOLD_EXIT_SEGMENTS_ARE_CONTIGUOUS_AND_MATCH_DECLARED_INTERVALS",
            motion["x-invariants"],
        )
        asset = artifacts["ASSET_PLAN"]["schema"]
        self.assertIn("assets", asset["required"])
        asset_item = asset["properties"]["assets"]["items"]
        self.assertTrue(
            {
                "asset_id",
                "object_id",
                "sentence_ids",
                "claim_ids",
                "visual_intent_id",
                "asset_ref",
                "asset_sha256",
                "provenance_refs",
                "provenance_sha256s",
                "local_build_recipe",
                "generation_receipt_ref",
                "generation_receipt_sha256",
            }.issubset(asset_item["required"])
        )
        local_recipe = asset_item["properties"]["local_build_recipe"]
        self.assertTrue(
            {
                "implementation_ref",
                "implementation_sha256",
                "input_manifest_ref",
                "input_manifest_sha256",
                "command_receipt_ref",
                "command_receipt_sha256",
                "output_ref",
                "output_sha256",
            }.issubset(local_recipe["required"])
        )
        self.assertNotIn(
            "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS",
            asset["x-invariants"],
        )
        binding = artifacts["ASSET_BINDING_RECEIPT"]
        self.assertIn(
            "MOTION_OBJECT_IDS_EQUAL_ASSET_OBJECT_IDS",
            binding["schema"]["x-invariants"],
        )
        self.assertEqual(
            binding["depends_on_artifact_ids"],
            [
                artifacts["ASSET_PLAN"]["artifact_id"],
                artifacts["NARRATION_SCRIPT"]["artifact_id"],
                artifacts["FUNCTION_SCENARIO_EFFECT_MATRIX"]["artifact_id"],
                artifacts["OBJECT_MOTION_IR"]["artifact_id"],
            ],
        )
        render_schema = artifacts["LOCAL_RENDER_RECEIPT"]["schema"]
        render_required = render_schema["required"]
        media_required = artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["schema"]["required"]
        self.assertTrue(
            {
                "render_trace_ref",
                "render_trace_sha256",
                "rendered_motion_curve_ids",
                "render_trace_sample_count",
                "rendered_semantic_bindings",
                "render_input_manifest_ref",
                "render_input_manifest_sha256",
                "composition_ref",
                "composition_sha256",
                "render_command_receipt_ref",
                "render_command_receipt_sha256",
                "tts_receipt_ref",
                "tts_receipt_sha256",
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "dependency_manifest_ref",
                "dependency_manifest_sha256",
            }.issubset(render_required)
        )
        self.assertIn(
            "RENDER_INPUT_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES",
            render_schema["x-invariants"],
        )
        self.assertTrue(
            {
                "video_ref",
                "video_sha256",
                "ffprobe_receipt_ref",
                "ffprobe_receipt_sha256",
                "render_receipt_ref",
                "render_receipt_sha256",
                "tts_receipt_ref",
                "tts_receipt_sha256",
                "alignment_receipt_ref",
                "alignment_receipt_sha256",
                "dependency_manifest_ref",
                "dependency_manifest_sha256",
                "motion_probe_ref",
                "motion_probe_sha256",
                "observed_dynamic_frame_count",
                "observed_scene_transition_count",
                "observed_motion_objects",
            }.issubset(media_required)
        )
        observed_motion = artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["schema"][
            "properties"
        ]["observed_motion_objects"]
        self.assertTrue(
            {
                "asset_id",
                "sentence_ids",
                "claim_ids",
                "visual_intent_id",
                "audio_anchor_id",
            }.issubset(observed_motion["items"]["required"])
        )
        self.assertEqual(
            observed_motion["items"]["properties"]["changed_frame_count"][
                "minimum"
            ],
            0,
        )
        self.assertIn(
            "EACH_DECLARED_OBJECT_HAS_NONZERO_PROBED_MOTION",
            artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["schema"]["x-invariants"],
        )
        self.assertTrue(
            {
                "DEPENDENCY_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES",
                "DEPENDENCY_MANIFEST_BINDS_EXACT_DECLARED_ARTIFACT_DEPENDENCIES",
            }.issubset(render_schema["x-invariants"])
        )
        self.assertTrue(
            {
                "DEPENDENCY_MANIFEST_SHA256_MATCHES_REFERENCED_BYTES",
                "DEPENDENCY_MANIFEST_BINDS_EXACT_DECLARED_ARTIFACT_DEPENDENCIES",
            }.issubset(
                artifacts["MEDIA_ACCEPTANCE_RECEIPT"]["schema"]["x-invariants"]
            )
        )
        self.assertEqual(
            observed_motion["items"]["properties"]["max_visual_delta"][
                "exclusiveMinimum"
            ],
            0,
        )
        gate = artifacts["TARGET_SKILL_EXECUTION_GATE_RECEIPT"]["schema"]
        self.assertGreater(len(gate["x-invariants"]), 0)
        self.assertTrue(
            {
                "authorization_receipt_sha256",
                "authorization_scope",
                "authorization_freshness",
                "authorized_job_id",
                "authorized_commit_sha",
                "authorized_input_manifest_sha256",
                "current_input_manifest_sha256",
                "authorized_environment_id",
                "authorized_environment_manifest_ref",
                "authorized_environment_manifest_sha256",
                "current_environment_manifest_sha256",
                "authorized_output_root_ref",
                "authorized_output_manifest_sha256",
                "current_output_manifest_sha256",
                "output_receipt_ref",
                "output_receipt_sha256",
                "execution_receipt_sha256",
                "authorization_consumed",
            }.issubset(gate["required"])
        )
        stage_artifacts = [
            artifact
            for artifact in all_artifacts
            if artifact["artifact_kind"] == "RESUMABLE_STAGE_RECEIPT"
        ]
        artifact_by_id = {
            artifact["artifact_id"]: artifact for artifact in all_artifacts
        }
        for stage_id in ("CONTENT_QA", "PACKAGING"):
            stage_artifact = next(
                artifact
                for artifact in stage_artifacts
                if artifact["expected_stage_id"] == stage_id
            )
            dependency_kinds = {
                artifact_by_id[dependency_id]["artifact_kind"]
                for dependency_id in stage_artifact["depends_on_artifact_ids"]
            }
            self.assertNotIn("FIXTURE_ACCEPTANCE_RECEIPT", dependency_kinds)
            self.assertIn("BEFORE_AFTER_DEMO_CONTRACT", dependency_kinds)
            self.assertIn("MEDIA_ACCEPTANCE_RECEIPT", dependency_kinds)
        self.assertEqual(len(stage_artifacts), len(RESUMABLE_STAGE_ORDER))
        self.assertEqual(
            [artifact["expected_stage_id"] for artifact in stage_artifacts],
            list(RESUMABLE_STAGE_ORDER),
        )
        self.assertEqual(
            [artifact["expected_stage_index"] for artifact in stage_artifacts],
            list(range(len(RESUMABLE_STAGE_ORDER))),
        )
        self.assertIsNone(stage_artifacts[0]["expected_previous_stage_id"])
        for previous, current in zip(stage_artifacts, stage_artifacts[1:]):
            self.assertEqual(
                current["expected_previous_stage_id"],
                previous["expected_stage_id"],
            )
            self.assertIn(
                previous["artifact_id"],
                current["depends_on_artifact_ids"],
            )
        resumable = stage_artifacts[-1]["schema"]
        self.assertGreater(len(resumable["x-invariants"]), 0)
        self.assertTrue(
            {
                "stage_id",
                "stage_index",
                "previous_stage_id",
                "required_stage_ids",
                "stage_receipt_set_id",
                "input_manifest_sha256",
                "output_manifest_sha256",
                "event_payload_sha256",
                "completed_side_effect_ids",
                "attempted_side_effect_ids",
                "completed_idempotency_keys",
                "attempted_idempotency_keys",
                "current_input_hashes_sha256",
                "receipt_input_hashes_sha256",
            }.issubset(resumable["required"])
        )
        for artifact in all_artifacts:
            if artifact["artifact_kind"] in {
                "NARRATION_SCRIPT",
                *kinds,
            }:
                oracle = artifact["oracle"]
                self.assertTrue(oracle["evaluator_id"])
                self.assertEqual(
                    oracle["evaluator_registry_ref"],
                    "harness-resource://candidate/validation/ORACLE_EVALUATOR_REGISTRY.json",
                )
        registry = oracle_evaluator_registry(
            set(artifacts), list(artifacts.values())
        )
        declared = {
            (kind, invariant)
            for kind, artifact in artifacts.items()
            for invariant in artifact["schema"].get("x-invariants", [])
        }
        covered = {
            (row["artifact_kind"], row["invariant_id"])
            for row in registry["invariant_negative_case_matrix"]
        }
        self.assertEqual(covered, declared)
        for row in registry["invariant_negative_case_matrix"]:
            self.assertTrue(row["mutation"]["target_ref"].startswith("/"))
            self.assertTrue(row["applicable_schema_sha256s"])
            self.assertEqual(
                row["mutation"]["post_mutation_json_schema_expected"],
                "PASS",
            )
            self.assertEqual(
                {
                    item["schema_sha256"]
                    for item in row["mutation"]["schema_instances"]
                },
                set(row["applicable_schema_sha256s"]),
            )
            self.assertEqual(
                row["mutation"]["operation"],
                "DERIVE_VALUE_FROM_PASSING_BASE",
            )
            self.assertTrue(row["mutation"]["derivation_recipe"]["strategy"])
            self.assertEqual(
                row["mutation"]["post_mutation_required_failed_invariant_ids"],
                [row["invariant_id"]],
            )
            self.assertEqual(
                row["mutation"]["outside_allowed_failure_set_expected"],
                "PASS",
            )
            self.assertEqual(
                row["mutation"]["proof_status"],
                "REQUIRES_EXTERNAL_LAB_REPLAY",
            )
            self.assertTrue(
                all(
                    item["counterexample_replay_required"] is True
                    and item["counterexample_proof_status"]
                    == "NOT_CLAIMED_UNTIL_EXTERNAL_LAB_REPLAY"
                    and "schema_valid_witness" not in item
                    for item in row["mutation"]["schema_instances"]
                )
            )
            self.assertFalse(row["side_effects_allowed"])

        schema_native = {
            row["constraint_id"]: row
            for row in registry["schema_native_negative_case_matrix"]
        }
        self.assertEqual(
            schema_native["EVERY_SENTENCE_HAS_A_VISUAL_INTENT"]["mutation"][
                "post_mutation_json_schema_expected"
            ],
            "FAIL",
        )
        self.assertEqual(
            schema_native["EVERY_ASSET_HAS_EXACTLY_ONE_ROUTE"][
                "expected_failure"
            ],
            "ARTIFACT_SCHEMA_REJECTED",
        )

        mutation_by_invariant = {
            row["invariant_id"]: row["mutation"]
            for row in registry["invariant_negative_case_matrix"]
        }
        self.assertNotEqual(
            mutation_by_invariant["FIRST_SHOT_STARTS_AT_ZERO"]["target_ref"],
            mutation_by_invariant[
                "FULL_TIMELINE_CONTIGUOUS_NO_GAPS_OR_OVERLAPS"
            ]["target_ref"],
        )
        self.assertEqual(
            mutation_by_invariant["FINAL_SHOT_END_EQUALS_DURATION_SECONDS"][
                "target_ref"
            ],
            "/duration_seconds",
        )
        self.assertEqual(
            mutation_by_invariant[
                "FINAL_SHOT_END_EQUALS_DURATION_SECONDS"
            ]["derivation_recipe"]["comparison_ref"],
            "/shots/-1/end_seconds",
        )
        self.assertEqual(
            mutation_by_invariant[
                "EVERY_MOTION_SEGMENT_HAS_DISTINCT_FROM_AND_TO_STATE"
            ]["derivation_recipe"]["strategy"],
            "COPY_VALUE_FROM_JSON_POINTER",
        )
        for row in registry["invariant_negative_case_matrix"]:
            recipe = row["mutation"]["derivation_recipe"]
            self.assertNotEqual(
                recipe["strategy"],
                "EVALUATOR_GUIDED_EXACT_COUNTEREXAMPLE_SEARCH",
            )
            if recipe["strategy"] == (
                "DETERMINISTIC_BOUNDED_EXACT_COUNTEREXAMPLE_ENUMERATION"
            ):
                self.assertGreater(recipe["maximum_candidates"], 0)
                self.assertTrue(recipe["candidate_generation_order"])
                self.assertEqual(
                    recipe["candidate_sort"],
                    "CANONICAL_JSON_UTF8_LEXICOGRAPHIC",
                )

        value["target"]["architecture_input"]["failure_returns"].append(
            "UNROUTED_ARCHITECTURE_FAILURE"
        )
        self.assertIn(
            "ARCHITECTURE_FAILURE_RETURN_UNROUTED",
            {
                finding["code"]
                for finding in validate_explicit_production_contracts(value)
            },
        )

    def test_local_render_keeps_renderer_identity_separate_from_content_job(
        self,
    ) -> None:
        value = deepcopy(self.ir)
        sources = [
            {
                "source_id": "SRC-DIRECT-VIDEO-SHOTCRAFT",
                "repository_url": "https://github.com/Vincentwei1021/video-shotcraft",
                "revision": "main",
                "commit_sha": "1" * 40,
                "git_tree_oid": "2" * 40,
                "tree_sha256": "3" * 64,
                "sha256": "3" * 64,
                "license_spdx": "Apache-2.0",
            },
            {
                "source_id": "SRC-REFERENCE-AI-DAILY",
                "repository_url": "https://github.com/davidliuzhibo/AI_Daily",
                "revision": "main",
                "commit_sha": "4" * 40,
                "git_tree_oid": "5" * 40,
                "tree_sha256": "6" * 64,
                "sha256": "6" * 64,
                "license_spdx": "NOASSERTION",
            },
            {
                "source_id": "SRC-REFERENCE-GC-POSTER",
                "repository_url": "https://github.com/LiamGvchi/gc-minimal-zine-poster",
                "revision": "main",
                "commit_sha": "7" * 40,
                "git_tree_oid": "8" * 40,
                "tree_sha256": "9" * 64,
                "sha256": "9" * 64,
                "license_spdx": "MIT",
            },
        ]
        value["sources"] = sources
        value["atoms"] = [
            {
                "atom_id": "ATOM-RENDER",
                "text_or_lossless_paraphrase": "Render every job with the pinned local renderer.",
                "owner": "MAIN_HARNESS_BUILD",
                "verification_mode": "LOCAL_RENDER_RECEIPT",
            }
        ]
        value["coverage_edges"] = normalize_ir_coverage(value)["coverage_edges"]
        value["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        value["target"]["artifact_schema_catalog"] = {
            "ATOM-RENDER": {
                "artifact_kind": "LOCAL_RENDER_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": [
                        "repository_url",
                        "commit_sha",
                        "tree_sha256",
                        "license_spdx",
                        "status",
                    ],
                    "properties": {
                        "repository_url": {"const": sources[0]["repository_url"]},
                        "commit_sha": {"const": sources[0]["commit_sha"]},
                        "tree_sha256": {"const": sources[0]["tree_sha256"]},
                        "license_spdx": {"const": sources[0]["license_spdx"]},
                        "status": {"const": "PASS"},
                    },
                },
            }
        }

        compiled = compile_declared_production_contracts(value)
        renders = [
            artifact
            for atom in compiled["atoms"]
            for obligation in atom["production_contract"]["workpack_obligations"]
            for artifact in obligation["artifact_obligations"]
        ]
        self.assertEqual(len(renders), 3)
        for artifact in renders:
            properties = artifact["schema"]["properties"]
            self.assertEqual(
                properties["renderer_source_id"]["const"],
                "SRC-DIRECT-VIDEO-SHOTCRAFT",
            )
            self.assertEqual(
                properties["renderer_repository_url"]["const"],
                sources[0]["repository_url"],
            )
            self.assertEqual(
                properties["renderer_commit_sha"]["const"],
                sources[0]["commit_sha"],
            )
            self.assertEqual(
                properties["renderer_tree_sha256"]["const"],
                sources[0]["tree_sha256"],
            )
            self.assertEqual(
                properties["renderer_license_spdx"]["const"],
                sources[0]["license_spdx"],
            )
            self.assertEqual(
                properties["content_repository_url"]["const"],
                next(
                    item["repository_url"]
                    for item in sources
                    if item["source_id"] == artifact["source_id"]
                ),
            )
            self.assertEqual(
                properties["repository_url"]["const"],
                sources[0]["repository_url"],
            )

    def test_case_oracles_are_exact_per_fixture_and_lab_build_is_concrete(self) -> None:
        for index in range(1, 4):
            source = deepcopy(self.ir["sources"][0])
            source.update(
                {
                    "source_id": f"SRC-FIXTURE-{index}",
                    "repository_url": f"https://github.com/example/fixture-{index}",
                    "revision": "main",
                    "commit_sha": str(index) * 40,
                    "git_tree_oid": str(index + 3) * 40,
                    "tree_sha256": source["sha256"],
                    "license_spdx": "MIT",
                    "scope": "test fixture",
                }
            )
            self.ir["sources"].append(source)
        self.compile()

        acceptance = json.loads(
            (self.candidate / "validation/ACCEPTANCE_CASES.json").read_text(
                encoding="utf-8"
            )
        )
        negative = json.loads(
            (self.candidate / "validation/NEGATIVE_CASES.json").read_text(
                encoding="utf-8"
            )
        )
        case = acceptance["cases"][0]
        fixture = json.loads(
            (
                self.candidate
                / case["fixture_ref"].removeprefix("harness-resource://candidate/")
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            {
                "assertion_manifest_sha256",
                "artifact_manifest_sha256",
                "source_job_manifest_sha256",
                "evaluator_id",
            }.issubset(fixture["oracle_bindings"])
        )
        for job in fixture["input"]["fixture_jobs"]:
            self.assertTrue(
                {
                    "expected_function",
                    "expected_scenario",
                    "expected_effect",
                    "demo_contract_ref",
                }.issubset(job)
            )
        self.assertNotEqual(
            case["result_schema_ref"],
            "harness-resource://candidate/validation/schemas/CASE_RESULT.schema.json",
        )
        case_schema = json.loads(
            (
                self.candidate
                / case["result_schema_ref"].removeprefix(
                    "harness-resource://candidate/"
                )
            ).read_text(encoding="utf-8")
        )
        assertion_results = case_schema["properties"]["assertion_results"]
        self.assertEqual(assertion_results["minItems"], len(fixture["assertions"]))
        self.assertEqual(assertion_results["maxItems"], len(fixture["assertions"]))
        self.assertIn("source_job_bindings", case_schema["required"])
        self.assertIn("artifact_checks", case_schema["required"])

        negative_case = negative["cases"][0]
        negative_schema = json.loads(
            (
                self.candidate
                / negative_case["result_schema_ref"].removeprefix(
                    "harness-resource://candidate/"
                )
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            {
                "observed_failure_code",
                "expected_failure_observed",
                "side_effect_receipt_ref",
                "side_effects_started",
            }.issubset(negative_schema["required"])
        )
        self.assertEqual(
            negative_schema["properties"]["observed_failure_code"]["const"],
            negative_case["expected_failure"],
        )
        registry = json.loads(
            (
                self.candidate / "validation/ORACLE_EVALUATOR_REGISTRY.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("EXACT_CASE_SET_ORACLE_V1", registry["evaluators"])
        for workpack_id in ("LAB-PROTOCOL", "LAB-CLI", "LAB-FIXTURES"):
            bundle = json.loads(
                (
                    self.candidate
                    / "project_start_packages/external_lab/task_bundles"
                    / f"{workpack_id}.task_bundle.json"
                ).read_text(encoding="utf-8")
            )
            contract = bundle["lab_case_execution_contract"]
            self.assertIn(
                "harness-resource://candidate/validation/schemas/CASE_RESULT.schema.json",
                contract["required_refs"],
            )
            self.assertIn("LAB-EVALUATE-CASE-ORACLE", contract["required_command_ids"])
            self.assertIn("EXACT_SOURCE_JOBS_MATCH", contract["assertion_operators"])
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

    def test_validator_rejects_prose_only_negative_mutation(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/NEGATIVE_CASES.json"
        negative = json.loads(path.read_text(encoding="utf-8"))
        negative["cases"][0]["input_fixture"]["mutation"] = {
            "operation": "INJECT_DECLARED_VIOLATION",
            "target_ref": "validation-input://narrative-only",
            "invalid_value": {"declared_violation": "missing alignment"},
            "expected_failure": negative["cases"][0]["expected_failure"],
        }
        path.write_text(
            json.dumps(negative, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "NONEXECUTABLE_NEGATIVE_FIXTURE_SCHEMA_INVALID",
            self.finding_codes(),
        )

    def test_validator_rejects_unresolvable_negative_mutation_binding(
        self,
    ) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/NEGATIVE_CASES.json"
        negative = json.loads(path.read_text(encoding="utf-8"))
        mutation = negative["cases"][0]["input_fixture"]["mutation"]
        mutation.pop("target_binding")
        path.write_text(
            json.dumps(negative, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "NONEXECUTABLE_NEGATIVE_FIXTURE_SCHEMA_INVALID",
            self.finding_codes(),
        )

    def test_generated_negative_mutations_are_concrete_and_machine_applicable(
        self,
    ) -> None:
        self.ir["negative_cases"].append(
            {
                "case_id": "NEG-MULTI-SKILL-OR-DURATION-DRIFT",
                "atom_ids": ["ATOM-001"],
                "description": (
                    "Reject multiple input Skills or an output outside the "
                    "frozen 175-185 second duration contract."
                ),
                "expected_failure": "VIDEO_CONTRACT_REJECTED",
            }
        )
        self.ir["negative_cases"].append(
            {
                "case_id": "NEG-UNAUTHORIZED-TARGET-EXECUTION-OR-FALSE-RESUME",
                "atom_ids": ["ATOM-001"],
                "description": (
                    "Reject disabled, broad, stale, or replayed target Skill execution."
                ),
                "expected_failure": "TARGET_SKILL_EXECUTION_DISABLED",
            }
        )
        source = deepcopy(self.ir["sources"][0])
        source.update(
            {
                "source_id": "SRC-NEGATIVE-FIXTURE",
                "repository_url": "https://github.com/example/negative-fixture",
                "revision": "main",
                "commit_sha": "1" * 40,
                "git_tree_oid": "2" * 40,
                "tree_sha256": source["sha256"],
                "license_spdx": "MIT",
                "scope": "negative mutation regression fixture",
            }
        )
        self.ir["sources"].append(source)
        self.configure_derived_media_atoms(
            (
                "SOURCE_FREEZE_RECEIPT",
                "FUNCTION_SCENARIO_EFFECT_MATRIX",
                "ASSET_PLAN",
                "BEFORE_AFTER_DEMO_CONTRACT",
                "LOCAL_TTS_RECEIPT",
                "AUDIO_ALIGNMENT_RECEIPT",
                "OBJECT_MOTION_IR",
                "TARGET_SKILL_EXECUTION_GATE_RECEIPT",
                "RESUMABLE_STAGE_RECEIPT",
                "LOCAL_RENDER_RECEIPT",
                "MEDIA_ACCEPTANCE_RECEIPT",
            )
        )
        self.compile()
        negative = json.loads(
            (self.candidate / "validation/NEGATIVE_CASES.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertGreaterEqual(len(negative["cases"]), 20)
        for case in negative["cases"]:
            mutations = [
                case["input_fixture"]["mutation"],
                *[
                    item["mutation"]
                    for item in case["input_fixture"]["mutation_variants"]
                ],
            ]
            for mutation in mutations:
                self.assertNotEqual(
                    mutation["operation"], "INJECT_DECLARED_VIOLATION"
                )
                self.assertFalse(
                    mutation["target_ref"].startswith("validation-input://")
                )
                self.assertTrue(mutation["violated_constraint"])
                self.assertEqual(
                    mutation["expected_failure"], case["expected_failure"]
                )
                binding = mutation["target_binding"]
                self.assertIn(
                    binding["resolver"],
                    {
                        "ARTIFACT_MANIFEST_SCHEMA_POINTER_V1",
                        "FIXTURE_INPUT_JSON_POINTER_V1",
                        "EXECUTION_INPUT_JSON_POINTER_V1",
                    },
                )
                self.assertTrue(binding["json_pointers"])
                self.assertTrue(
                    all(
                        pointer.startswith("/")
                        for pointer in binding["json_pointers"]
                    )
                )
                if binding["resolver"] == (
                    "ARTIFACT_MANIFEST_SCHEMA_POINTER_V1"
                ):
                    self.assertTrue(binding["artifact_ids"])
                    self.assertEqual(
                        len(binding["artifact_ids"]),
                        len(binding["artifact_refs"]),
                    )
                else:
                    self.assertTrue(binding["base_input_ref"])
        manifest_hashes = [
            case["mutation_manifest_sha256"] for case in negative["cases"]
        ]
        self.assertEqual(len(manifest_hashes), len(set(manifest_hashes)))
        multi = next(
            case
            for case in negative["cases"]
            if case["case_id"] == "NEG-MULTI-SKILL-OR-DURATION-DRIFT"
        )
        duration = next(
            item["mutation"]
            for item in multi["input_fixture"]["mutation_variants"]
            if item["variant_id"] == "DURATION-DRIFT"
        )
        self.assertEqual(duration["invalid_value"], 186)
        self.assertEqual(
            duration["violated_constraint"],
            {"minimum": 175, "maximum": 185},
        )
        self.assertEqual(
            duration["target_binding"]["artifact_kind"],
            "MEDIA_ACCEPTANCE_RECEIPT",
        )
        self.assertEqual(
            duration["target_binding"]["json_pointers"],
            ["/duration_seconds"],
        )
        release_skip = next(
            case
            for case in negative["cases"]
            if case["case_id"] == "NEG-HF28-RELEASE-SKIP"
        )
        b0_b1_order = next(
            case
            for case in negative["cases"]
            if case["case_id"] == "NEG-HF28-B0-B1-ORDER"
        )
        self.assertNotEqual(
            release_skip["mutation_manifest_sha256"],
            b0_b1_order["mutation_manifest_sha256"],
        )
        self.assertEqual(
            {
                item["variant_id"]
                for item in b0_b1_order["input_fixture"]["mutation_manifest"]
            },
            {
                "B0-PREFILLED-ARTIFACT-HASH",
                "B1-BEFORE-IMMUTABLE-ARTIFACT-BUILD",
            },
        )
        target_gate_case = next(
            case
            for case in negative["cases"]
            if case["expected_failure"] == "TARGET_SKILL_EXECUTION_DISABLED"
        )
        self.assertEqual(
            {
                item["variant_id"]
                for item in target_gate_case["input_fixture"][
                    "mutation_variants"
                ]
            },
            {
                "DENIED-GATE-SIDE-EFFECT",
                "PROGRAM-WIDE-AUTHORIZATION-SUBSTITUTION",
                "STALE-AUTHORIZATION-OR-INPUT-HASH",
                "CONSUMED-AUTHORIZATION-REPLAY",
                "FALSE-RESUME-SIDE-EFFECT-REPLAY",
            },
        )
        mutation_input = target_gate_case["input_fixture"]
        self.assertEqual(
            mutation_input["mutation_manifest"],
            mutation_input["mutation_variants"],
        )
        mutation_manifest_sha256 = hashlib.sha256(
            json.dumps(
                mutation_input["mutation_manifest"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            mutation_input["mutation_manifest_sha256"],
            mutation_manifest_sha256,
        )
        self.assertEqual(
            target_gate_case["mutation_manifest_sha256"],
            mutation_manifest_sha256,
        )
        self.assertTrue(mutation_input["artifact_expectations"])
        self.assertTrue(mutation_input["fixture_jobs"])

        result_schema = json.loads(
            (
                self.candidate
                / target_gate_case["result_schema_ref"].removeprefix(
                    "harness-resource://candidate/"
                )
            ).read_text(encoding="utf-8")
        )
        variant_results = result_schema["properties"][
            "mutation_variant_results"
        ]
        self.assertEqual(variant_results["minItems"], 5)
        self.assertEqual(variant_results["maxItems"], 5)
        self.assertEqual(len(variant_results["allOf"]), 5)
        self.assertTrue(
            {
                "base_input_ref",
                "base_input_sha256",
                "mutated_input_ref",
                "mutated_input_sha256",
                "mutation_receipt_ref",
                "mutation_receipt_sha256",
                "command_receipt_ref",
                "command_receipt_sha256",
                "validator_finding_ref",
                "validator_finding_sha256",
                "side_effect_receipt_ref",
                "side_effect_receipt_sha256",
            }.issubset(variant_results["items"]["required"])
        )

        self.make_candidate_writable()
        removed_variant = mutation_input["mutation_variants"].pop()
        mutation_input["mutation_manifest"] = list(
            mutation_input["mutation_variants"]
        )
        mutation_input["mutation_manifest_sha256"] = hashlib.sha256(
            json.dumps(
                mutation_input["mutation_manifest"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        target_gate_case["mutation_manifest_sha256"] = mutation_input[
            "mutation_manifest_sha256"
        ]
        (self.candidate / "validation/NEGATIVE_CASES.json").write_text(
            json.dumps(negative, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        self.assertEqual(
            removed_variant["variant_id"],
            "FALSE-RESUME-SIDE-EFFECT-REPLAY",
        )
        self.assertIn(
            "NONEXECUTABLE_NEGATIVE_FIXTURE_SCHEMA_INVALID",
            self.finding_codes(),
        )

    def test_validator_rejects_duplicate_negative_mutation_manifests(
        self,
    ) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/NEGATIVE_CASES.json"
        negative = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(negative["cases"]), 2)
        negative["cases"][1]["mutation_manifest_sha256"] = negative["cases"][0][
            "mutation_manifest_sha256"
        ]
        path.write_text(
            json.dumps(negative, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "NEGATIVE_MUTATION_MANIFEST_SET_NOT_UNIQUE",
            self.finding_codes(),
        )

    def test_content_evidence_negative_targets_real_demo_receipt_field(
        self,
    ) -> None:
        self.ir["negative_cases"] = [
            {
                "case_id": "NEG-DEMO-PROVENANCE",
                "atom_ids": ["ATOM-001"],
                "description": "Reject an authorized run without its receipt.",
                "expected_failure": "CONTENT_EVIDENCE_MISMATCH",
            }
        ]
        self.compile()
        negative = json.loads(
            (self.candidate / "validation/NEGATIVE_CASES.json").read_text(
                encoding="utf-8"
            )
        )
        case = next(
            item
            for item in negative["cases"]
            if item["case_id"] == "NEG-DEMO-PROVENANCE"
        )
        mutation = case["input_fixture"]["mutation"]

        self.assertEqual(
            mutation["target_ref"],
            "before_after_demo.target_skill_execution_receipt_ref",
        )
        self.assertEqual(
            mutation["violated_constraint"]["when"]["provenance_state"],
            "AUTHORIZED_TARGET_SKILL_RUN",
        )

    def test_validator_rejects_untyped_assertion_results(self) -> None:
        self.compile()
        self.make_candidate_writable()
        path = self.candidate / "validation/schemas/CASE_RESULT.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["properties"]["assertion_results"].pop("items")
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.assertIn("CASE_EXECUTION_MANIFEST_INVALID", self.finding_codes())

    def test_validator_rejects_weakened_case_specific_exact_set_schema(self) -> None:
        self.compile()
        self.make_candidate_writable()
        acceptance_path = self.candidate / "validation/ACCEPTANCE_CASES.json"
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        case = acceptance["cases"][0]
        schema_path = self.candidate / case["result_schema_ref"].removeprefix(
            "harness-resource://candidate/"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assertions = schema["properties"]["assertion_results"]
        assertions["maxItems"] = assertions["minItems"] + 1
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        weakened_sha256 = hashlib.sha256(schema_path.read_bytes()).hexdigest()
        case["result_schema_sha256"] = weakened_sha256
        case["oracle_contract"]["result_schema_sha256"] = weakened_sha256
        acceptance_path.write_text(
            json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.assertIn(
            "EXECUTABLE_CASE_ORACLE_INCOMPLETE",
            self.finding_codes(),
        )

    def test_baseline_migration_targets_resolve_to_produced_artifacts(self) -> None:
        del self.ir["atoms"][0]["production_contract"]
        self.ir["target"]["production_contract_derivation_policy"] = (
            DETERMINISTIC_DERIVATION_POLICY
        )
        self.ir["target"]["artifact_schema_catalog"] = {
            "ATOM-001": {
                "artifact_name": "architecture_lock",
                "artifact_kind": "LOCK_RECEIPT",
                "schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "PASS"}},
                },
            }
        }
        baseline_source = self.ir["sources"][0]
        self.ir["target"]["baseline_migration_contract"] = {
            "baseline_source_id": baseline_source["source_id"],
            "baseline_version": "0.9.0",
            "target_version": "1.0.0",
            "disposition_rows": [
                {
                    "baseline_capability_id": "ARCHITECTURE_LOCKING",
                    "target_disposition": "UPGRADE",
                    "target_artifact_ids": ["ART-ATOM-001-MB-P4"],
                    "regression_case_ids": [
                        self.ir["acceptance_cases"][0]["case_id"]
                    ],
                    "rationale": "Bind the baseline capability to a produced artifact.",
                }
            ],
        }

        self.compile()

        matrix = json.loads(
            (
                self.candidate
                / "canonical_sources/BASELINE_MIGRATION_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        row = matrix["disposition_rows"][0]
        self.assertEqual(
            row["declared_target_artifact_ids"], ["ART-ATOM-001-MB-P4"]
        )
        self.assertEqual(
            row["target_artifact_ids"], ["ART-ATOM-001-MB-P1"]
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")

        self.make_candidate_writable()
        matrix_path = (
            self.candidate / "canonical_sources/BASELINE_MIGRATION_MATRIX.json"
        )
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        matrix["disposition_rows"][0]["target_artifact_ids"] = [
            "ART-NOT-PRODUCED"
        ]
        matrix_path.write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.assertIn("BASELINE_MIGRATION_CONTRACT_INVALID", self.finding_codes())

    def test_baseline_migration_prefers_primary_video_artifacts(self) -> None:
        self.configure_derived_media_atoms(
            ("LOCAL_TTS_RECEIPT", "OBJECT_MOTION_IR")
        )
        acceptance_case_id = self.ir["acceptance_cases"][0]["case_id"]
        self.ir["target"]["baseline_migration_contract"] = {
            "baseline_source_id": self.ir["sources"][0]["source_id"],
            "baseline_version": "0.9.0",
            "target_version": "1.0.0",
            "disposition_rows": [
                {
                    "baseline_capability_id": "TTS_AND_SCENE_TIMING",
                    "target_disposition": "UPGRADE",
                    "target_artifact_ids": [
                        "ART-ATOM-DERIVED-1-MB-P4",
                        "ART-ATOM-DERIVED-2-MB-P4",
                    ],
                    "regression_case_ids": [acceptance_case_id],
                    "rationale": (
                        "Preserve the primary TTS and Motion IR behavior."
                    ),
                }
            ],
        }

        self.compile()

        matrix = json.loads(
            (
                self.candidate
                / "canonical_sources/BASELINE_MIGRATION_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (
                self.candidate
                / "canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json"
            ).read_text(encoding="utf-8")
        )
        resolved_kinds = [
            manifest["artifact_index"][artifact_id]["artifact_kind"]
            for artifact_id in matrix["disposition_rows"][0][
                "target_artifact_ids"
            ]
        ]
        self.assertEqual(
            resolved_kinds, ["LOCAL_TTS_RECEIPT", "OBJECT_MOTION_IR"]
        )
        motion_id = matrix["disposition_rows"][0]["target_artifact_ids"][1]
        motion_schema = manifest["artifact_index"][motion_id]["schema"]
        self.assertEqual(motion_schema["properties"]["shots"]["minItems"], 10)
        self.assertEqual(motion_schema["properties"]["shots"]["maxItems"], 14)

        self.make_candidate_writable()
        auxiliary_ids = {
            item["artifact_kind"]: artifact_id
            for artifact_id, item in manifest["artifact_index"].items()
            if item["artifact_kind"]
            in {"NARRATION_SCRIPT", "ASSET_BINDING_RECEIPT"}
        }
        matrix["disposition_rows"][0]["target_artifact_ids"] = [
            auxiliary_ids["NARRATION_SCRIPT"],
            auxiliary_ids["ASSET_BINDING_RECEIPT"],
        ]
        unhashed = dict(matrix)
        unhashed.pop("contract_sha256", None)
        matrix["contract_sha256"] = hashlib.sha256(
            json.dumps(
                unhashed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        matrix_path = (
            self.candidate
            / "canonical_sources/BASELINE_MIGRATION_MATRIX.json"
        )
        matrix_path.write_text(
            json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        self.assertIn("BASELINE_MIGRATION_CONTRACT_INVALID", self.finding_codes())


if __name__ == "__main__":
    unittest.main()
