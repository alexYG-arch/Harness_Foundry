"""Slice 09 Epoch 38 profile-aware Candidate generation preflight."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from harness_foundry_factory.compiler import (
    _apply_epoch4_default_route_selection,
    _validate_epoch4_generation_readiness,
    compile_requirement_architecture_contract,
    compile_start_package,
)
from harness_foundry_factory.core_validation import (
    _project_validated_core_evidence,
    validate_core,
)
from harness_foundry_factory.generation_readiness import (
    GenerationReadinessError,
    evaluate_generation_readiness,
)
from harness_foundry_factory.models import ContractGateError, content_sha256
from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.validator import (
    _check_candidate_execution_separation,
    _check_candidate_resource_uri_closure,
    _check_epoch38_charter_projection,
    _check_epoch38_generation_route,
    _check_epoch38_local_validation_report_receipt,
    _check_nonexecutable_negative_fixture_schema,
    _check_portable_runtime_dependency_closure,
    _external_authority_requirement_epoch,
    validate_candidate as run_candidate_validation,
)
from tests.permissions import make_path_writable, make_tree_writable


ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ID = "PROGRAM-SLICE09-SELF-CONTAINED"
CORE_ROUTES = [
    "MB-G0",
    "MB-P1",
    "MB-P2",
    "MB-P3",
    "MB-P4",
    "MB-RELEASE-CANDIDATE",
]
OPTIONAL_SECURITY_ROUTES = [
    "LINK-PROTOCOL",
    "LINK-CLI",
    "LINK-SELFTEST",
    "LINK-PREFLIGHT",
    "LINK-D",
    "LAB-PROTOCOL",
    "LAB-CLI",
    "LAB-FIXTURES",
    "LAB-SELFTEST",
    "LAB-CERTIFICATION",
]
EXCLUDED_RELEASE_STEPS = [
    "P4_CERTIFIED_RELEASE_LOCK",
    "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS",
    "LINKAGE_A_INTERFACE_COMPLETENESS",
    "LINKAGE_D_INSTALLED_HANDSHAKE",
]


class GenerationReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.temporary_root = Path(cls.temporary.name)
        fixture = _epoch38_fixture(cls.temporary_root / "candidate")
        cls.snapshot = fixture["snapshot"]
        cls.requirement_lock = fixture["requirement_lock"]
        cls.architecture = fixture["architecture_readback"]
        cls.architecture_lock = fixture["architecture_lock"]
        cls.compiled = fixture["compiled_contract"]

        # The gate fixture is non-executing. The official validator later runs
        # the exact selector and supplies the behavioral result independently.
        cls.validation = validate_core(execute_tests=False)
        cls.validation["status"] = "PASS"
        cls.validation["core_regression"]["status"] = "PASS"
        cls.validation["core_regression"]["tests_executed"] = True
        for item in cls.validation["selector_results"]:
            item["status"] = "PASS"
        for item in cls.validation["major_failure_path_matrix"]:
            item["status"] = "PASS"
        cls.validation["validation_sha256"] = _rehash(
            cls.validation, "validation_sha256"
        )
        cls.projection = _project_validated_core_evidence(cls.validation)

    @classmethod
    def tearDownClass(cls) -> None:
        make_tree_writable(cls.temporary_root)
        cls.temporary.cleanup()

    def _evaluate(
        self,
        *,
        snapshot: dict | None = None,
        requirement_lock: dict | None = None,
        architecture_readback: dict | None = None,
        architecture_lock: dict | None = None,
        compiled_contract: dict | None = None,
        validation: dict | None = None,
        projection: dict | None = None,
    ) -> dict:
        return evaluate_generation_readiness(
            self.snapshot if snapshot is None else snapshot,
            requirement_lock=(
                self.requirement_lock
                if requirement_lock is None
                else requirement_lock
            ),
            architecture_readback=(
                self.architecture
                if architecture_readback is None
                else architecture_readback
            ),
            architecture_lock=(
                self.architecture_lock
                if architecture_lock is None
                else architecture_lock
            ),
            compiled_contract=(
                self.compiled
                if compiled_contract is None
                else compiled_contract
            ),
            core_validation=self.validation if validation is None else validation,
            core_evidence_projection=(
                self.projection if projection is None else projection
            ),
        )

    def test_epoch38_authority_and_fresh_core_evidence_pass_read_only(self) -> None:
        candidate = Path(self.snapshot["requirement_ir"]["target"]["output_root"])
        self.assertFalse(candidate.exists())
        result = self._evaluate()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["bindings"]["requirement_ir_sha256"],
            self.snapshot["freeze"]["requirement_ir_sha256"],
        )
        self.assertEqual(
            result["bindings"]["requirement_lock_sha256"],
            self.requirement_lock["requirement_lock_sha256"],
        )
        self.assertEqual(
            result["bindings"]["architecture_lock_sha256"],
            self.architecture_lock["architecture_lock_sha256"],
        )
        self.assertEqual(
            result["bindings"]["compiled_contract_sha256"],
            self.compiled["compiled_contract_sha256"],
        )
        self.assertEqual(
            result["route_selection"]["optional_security_hardening"],
            "NOT_RUN",
        )
        self.assertFalse(result["route_selection"]["external_certification_claimed"])
        self.assertFalse(result["writes_performed"])
        self.assertFalse(result["candidate_or_execution_root_created"])
        self.assertFalse(candidate.exists())

    def test_successor_epoch39_passes_with_epoch38_profile_origin(self) -> None:
        fixture = _epoch38_fixture(
            self.temporary_root / "epoch39-successor-candidate",
            active_requirement_epoch=39,
        )
        result = self._evaluate(**fixture)
        _validate_epoch4_generation_readiness(
            fixture["snapshot"]["requirement_ir"], result
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["requirement_epoch"], 39)
        self.assertEqual(
            fixture["snapshot"]["requirement_ir"]["target"]["requirement_epoch"],
            38,
        )
        self.assertEqual(
            fixture["snapshot"]["requirement_ir"]["target"]
            ["epoch4_architecture_control_plane_contract"]["requirement_epoch"],
            38,
        )
        self.assertFalse(
            Path(
                fixture["snapshot"]["requirement_ir"]["target"]["output_root"]
            ).exists()
        )

    def test_successor_epoch39_mixed_active_bindings_fail_closed(self) -> None:
        expected_codes = {
            "snapshot": "GENERATION_REQUIREMENT_BINDING_STALE_OR_MIXED_EPOCH",
            "freeze": "GENERATION_REQUIREMENT_BINDING_STALE_OR_MIXED_EPOCH",
            "requirement_lock": "GENERATION_REQUIREMENT_LOCK_STALE",
            "architecture_readback": (
                "GENERATION_ARCHITECTURE_LOCK_STALE_OR_MIXED_EPOCH"
            ),
            "architecture_lock": (
                "GENERATION_ARCHITECTURE_LOCK_STALE_OR_MIXED_EPOCH"
            ),
            "compiled_contract": "GENERATION_COMPILED_CONTRACT_STALE",
        }
        for component, expected_code in expected_codes.items():
            with self.subTest(component=component):
                fixture = _epoch38_fixture(
                    self.temporary_root / f"epoch39-mixed-{component}",
                    active_requirement_epoch=39,
                )
                if component == "snapshot":
                    fixture["snapshot"]["requirement_epoch"] = 38
                elif component == "freeze":
                    fixture["snapshot"]["freeze"]["requirement_epoch"] = 38
                elif component == "requirement_lock":
                    lock = fixture["requirement_lock"]
                    lock["requirement_epoch"] = 38
                    lock["requirement_lock_sha256"] = _rehash(
                        lock, "requirement_lock_sha256"
                    )
                elif component == "architecture_readback":
                    readback = fixture["architecture_readback"]
                    readback["requirement_epoch"] = 38
                    lock = fixture["architecture_lock"]
                    lock["architecture_readback_sha256"] = content_sha256(readback)
                    lock["architecture_lock_sha256"] = _rehash(
                        lock, "architecture_lock_sha256"
                    )
                elif component == "architecture_lock":
                    lock = fixture["architecture_lock"]
                    lock["requirement_epoch"] = 38
                    lock["architecture_lock_sha256"] = _rehash(
                        lock, "architecture_lock_sha256"
                    )
                else:
                    compiled = fixture["compiled_contract"]
                    compiled["requirement_epoch"] = 38
                    compiled["compiled_contract_sha256"] = _rehash(
                        compiled, "compiled_contract_sha256"
                    )

                with self.assertRaises(GenerationReadinessError) as error:
                    self._evaluate(**fixture)
                self.assertEqual(error.exception.code, expected_code)

    def test_profile_lock_and_evidence_drift_fail_closed(self) -> None:
        stale_profile = deepcopy(self.snapshot)
        stale_profile["requirement_ir"]["target"][
            "operating_assurance_profile"
        ] = "EXTERNAL_CERTIFICATION"
        with self.assertRaises(GenerationReadinessError) as profile_error:
            self._evaluate(snapshot=stale_profile)
        self.assertIn("GENERATION_", profile_error.exception.code)

        stale_validation = deepcopy(self.validation)
        stale_validation["optional_security_hardening"] = "PASS"
        stale_validation["validation_sha256"] = _rehash(
            stale_validation, "validation_sha256"
        )
        with self.assertRaises(GenerationReadinessError) as evidence_error:
            self._evaluate(validation=stale_validation)
        self.assertEqual(
            evidence_error.exception.code,
            "GENERATION_CORE_VALIDATION_NOT_PASS",
        )

    def test_epoch38_local_profile_does_not_reactivate_historical_external_authority(self) -> None:
        self.assertEqual(
            _external_authority_requirement_epoch(self.snapshot["requirement_ir"]),
            0,
        )
        historical = {
            "target": {
                "human_review_v0_34_closure": {
                    "active_epochs": {"requirement_epoch": 35}
                }
            }
        }
        self.assertEqual(_external_authority_requirement_epoch(historical), 35)

    def test_service_gate_runs_before_any_output_or_staging_parent_write(self) -> None:
        snapshot = deepcopy(self.snapshot)
        candidate = Path(snapshot["requirement_ir"]["target"]["output_root"])
        before_parent = candidate.parent.exists()
        before_trace = snapshot.get("generation_trace")
        service = object.__new__(FactoryService)
        service._requirement_gaps = lambda _snapshot: []  # type: ignore[method-assign]

        def blocked(_snapshot: dict) -> dict:
            raise ContractGateError(
                "blocked before output write",
                details={"gate_code": "GENERATION_TEST_BLOCK"},
            )

        service._generation_readiness_from_snapshot = blocked  # type: ignore[method-assign]
        with self.assertRaises(ContractGateError):
            service._generate(
                snapshot,
                SimpleNamespace(payload={}),  # type: ignore[arg-type]
                "2026-08-12T00:00:00Z",
            )

        self.assertEqual(snapshot.get("generation_trace"), before_trace)
        self.assertEqual(candidate.parent.exists(), before_parent)
        self.assertFalse(candidate.exists())

    def test_epoch4_compiler_requires_readiness_before_staging_write(self) -> None:
        staging = self.temporary_root / "staging-must-remain-absent"
        candidate = Path(self.snapshot["requirement_ir"]["target"]["output_root"])
        self.assertFalse(staging.exists())
        self.assertFalse(candidate.exists())

        with self.assertRaisesRegex(ValueError, "prewrite readiness binding"):
            compile_start_package(
                self.snapshot["requirement_ir"],
                spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                staging_root=staging,
                candidate_root=candidate,
                created_at="2026-08-12T00:00:00Z",
                spec_lock={"content_sha256": "fixture", "files": {}},
                authority_provenance={},
            )

        self.assertFalse(staging.exists())
        self.assertFalse(candidate.exists())

    def test_real_compiler_writes_profile_before_route_projection(self) -> None:
        staging = self.temporary_root / "ordering-staging"
        candidate = self.temporary_root / "ordering-candidate"
        readiness = self._evaluate()

        class OrderingObserved(RuntimeError):
            pass

        def observe_route_projection(root: Path) -> None:
            profile_path = root / "EPOCH38_GENERATION_PROFILE.json"
            self.assertTrue(profile_path.is_file())
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertEqual(
                profile["generation_readiness_sha256"],
                readiness["generation_readiness_sha256"],
            )
            self.assertEqual(profile["bindings"], readiness["bindings"])
            raise OrderingObserved

        with patch(
            "harness_foundry_factory.compiler._apply_epoch4_default_route_selection",
            side_effect=observe_route_projection,
        ):
            with self.assertRaises(OrderingObserved):
                compile_start_package(
                    self.snapshot["requirement_ir"],
                    spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                    staging_root=staging,
                    candidate_root=candidate,
                    created_at="2026-08-12T00:00:00Z",
                    spec_lock={"content_sha256": "fixture", "files": {}},
                    authority_provenance={},
                    generation_readiness=readiness,
                )

        self.assertTrue(staging.is_dir())
        self.assertFalse(candidate.exists())

    def test_epoch48_nonexecuting_fixture_scope_preserves_live_write_rejection(
        self,
    ) -> None:
        candidate = self.temporary_root / "epoch48-negative-fixture-candidate"
        staging = self.temporary_root / "epoch48-negative-fixture-staging"
        fixture = _epoch38_fixture(
            candidate,
            active_requirement_epoch=48,
            program_id="PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE",
            target_id="HARNESS-FOUNDRY-V2-9-CHAT-FACTORY",
        )
        readiness = self._evaluate(**fixture)
        passing_report = {
            "status": "PASS",
            "blocking_findings": [],
            "validator_id": "TEST_EPOCH48_NEGATIVE_FIXTURE_VALIDATOR",
            "commands_executed": False,
            "checks": [
                {
                    "check_id": "FACTORY_LOCAL_SOURCE_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                },
                {
                    "check_id": "FACTORY_LOCAL_REQUIREMENT_IR_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                },
            ],
        }
        with patch(
            "harness_foundry_factory.validator.validate_candidate",
            return_value=passing_report,
        ), patch(
            "harness_foundry_factory.validator."
            "_validate_prepublication_staging_candidate",
            return_value=passing_report,
        ):
            compile_start_package(
                fixture["snapshot"]["requirement_ir"],
                spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                staging_root=staging,
                candidate_root=candidate,
                created_at="2026-08-27T00:00:00Z",
                spec_lock={"content_sha256": "fixture", "files": {}},
                authority_provenance={},
                generation_readiness=readiness,
            )

        self.assertEqual(
            _check_nonexecutable_negative_fixture_schema(candidate), []
        )
        self.assertNotIn(
            "CANDIDATE_IMMUTABILITY_VIOLATION",
            {
                finding["code"]
                for finding in _check_candidate_execution_separation(candidate)
            },
        )

        outside_fixture_path = candidate / "validation/LIVE_COMMAND_CONTRACT.json"
        make_path_writable(outside_fixture_path)
        outside_fixture_path.write_text(
            json.dumps(
                {
                    "fixture_kind": "NON_EXECUTABLE_JSON",
                    "input_fixture": {
                        "allowed_write_roots": ["harness-resource://candidate"]
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "CANDIDATE_IMMUTABILITY_VIOLATION",
            {
                finding["code"]
                for finding in _check_candidate_execution_separation(candidate)
            },
        )
        outside_fixture_path.unlink()

        negative_path = candidate / "validation/NEGATIVE_CASES.json"
        make_path_writable(negative_path)
        negative = json.loads(negative_path.read_text(encoding="utf-8"))
        write_root_case = next(
            case
            for case in negative["cases"]
            if case.get("case_id")
            == "NEG-V29-E45-WORKPACK-RUNTIME-WRITE-ROOT"
        )
        write_root_case.pop("expected_failure")
        negative_path.write_text(
            json.dumps(negative, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.assertIn(
            "NONEXECUTABLE_NEGATIVE_FIXTURE_SCHEMA_INVALID",
            {
                finding["code"]
                for finding in _check_nonexecutable_negative_fixture_schema(
                    candidate
                )
            },
        )

    def test_real_compiler_projects_epoch38_charter_and_validator_rejects_drift(
        self,
    ) -> None:
        candidate = self.temporary_root / "charter-projection-candidate"
        staging = self.temporary_root / "charter-projection-staging"
        fixture = _epoch38_fixture(candidate)
        readiness = self._evaluate(**fixture)
        passing_report = {
            "status": "PASS",
            "blocking_findings": [],
            "validator_id": "TEST_CHARTER_PROJECTION_VALIDATOR",
            "commands_executed": False,
            "checks": [
                {
                    "check_id": "FACTORY_LOCAL_SOURCE_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                },
                {
                    "check_id": "FACTORY_LOCAL_REQUIREMENT_IR_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                },
            ],
        }

        with patch(
            "harness_foundry_factory.validator.validate_candidate",
            return_value=passing_report,
        ), patch(
            "harness_foundry_factory.validator."
            "_validate_prepublication_staging_candidate",
            return_value=passing_report,
        ):
            compile_start_package(
                fixture["snapshot"]["requirement_ir"],
                spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                staging_root=staging,
                candidate_root=candidate,
                created_at="2026-08-12T00:00:00Z",
                spec_lock={"content_sha256": "fixture", "files": {}},
                authority_provenance={},
                generation_readiness=readiness,
            )

        charter_path = candidate / "PROGRAM_CHARTER.md"
        make_path_writable(charter_path)
        charter = charter_path.read_text(encoding="utf-8")
        self.assertIn("Implement usable local v2.9 engineering capability first", charter)
        self.assertIn("Package shape profile: `FULL`", charter)
        self.assertIn(
            "Assurance profile: `SELF_USE_LOCAL_TRUSTED_OPERATOR`", charter
        )
        self.assertIn(
            "`POST_IMPLEMENTATION_VALIDATION` P0-08", charter
        )
        self.assertIn(
            "`OPTIONAL_SECURITY_HARDENING` P0-09", charter
        )
        self.assertIn("External certification claimed: `false`", charter)
        self.assertEqual(_check_epoch38_charter_projection(candidate), [])

        charter_path.write_text(
            charter.replace(
                "`OPTIONAL_SECURITY_HARDENING` P0-09",
                "`CORE_IMPLEMENTATION` P0-09",
            ),
            encoding="utf-8",
        )
        self.assertIn(
            "EPOCH38_CHARTER_PROJECTION_MISSING",
            {
                finding["code"]
                for finding in _check_epoch38_charter_projection(candidate)
            },
        )

    def test_real_compiler_projects_disjoint_null_execution_root_identities(self) -> None:
        staging = self.temporary_root / "portable-identity-staging"
        candidate = Path(self.snapshot["requirement_ir"]["target"]["output_root"])
        planned_execution = candidate.with_name(
            f".{candidate.name}.hffactory-planned-execution-{PROGRAM_ID}"
        )
        readiness = self._evaluate()

        class PortableIdentityObserved(RuntimeError):
            pass

        def observe_validator(root: Path, **_kwargs: object) -> dict:
            context = json.loads((root / "START_CONTEXT.json").read_text())
            portability = json.loads(
                (root / "validation/PORTABILITY_MANIFEST.json").read_text()
            )
            projects = json.loads(
                (root / "THREE_PROJECT_PROGRAM_MANIFEST.json").read_text()
            )
            self.assertEqual(context["candidate_root"], "harness-resource://candidate")
            self.assertEqual(context["target_root"], "harness-resource://candidate")
            self.assertEqual(context["execution_root"], "harness-resource://execution")
            self.assertFalse(context["candidate_execution_root_overlap"])
            self.assertEqual(
                context["candidate_root_access"],
                "READ_ONLY_AFTER_ATOMIC_PUBLICATION",
            )
            self.assertEqual(
                portability["logical_roots"],
                {
                    "candidate": "harness-resource://candidate",
                    "execution": "harness-resource://execution",
                },
            )
            self.assertTrue(
                all(
                    str(item["root_abs"]).startswith("harness-resource://execution/")
                    for item in projects["projects"]
                )
            )
            leaked_local_paths = {
                path.relative_to(root).as_posix(): [
                    line.strip()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if str(candidate) in line or str(planned_execution) in line
                ][:3]
                for path in root.rglob("*")
                if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}
                and (
                    str(candidate) in path.read_text(encoding="utf-8")
                    or str(planned_execution) in path.read_text(encoding="utf-8")
                )
            }
            self.assertEqual(leaked_local_paths, {})
            raise PortableIdentityObserved

        with patch(
            "harness_foundry_factory.validator.validate_candidate",
            side_effect=observe_validator,
        ):
            with self.assertRaises(PortableIdentityObserved):
                compile_start_package(
                    self.snapshot["requirement_ir"],
                    spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                    staging_root=staging,
                    candidate_root=candidate,
                    created_at="2026-08-12T00:00:00Z",
                    spec_lock={"content_sha256": "fixture", "files": {}},
                    authority_provenance={},
                    generation_readiness=readiness,
                )

        self.assertTrue(staging.is_dir())
        self.assertFalse(candidate.exists())
        self.assertFalse(planned_execution.exists())

    def test_epoch4_planned_execution_identity_collision_fails_before_write(self) -> None:
        for collision_kind in ("DIRECTORY", "DANGLING_SYMLINK"):
            with self.subTest(collision_kind=collision_kind):
                staging = self.temporary_root / f"{collision_kind}-staging"
                candidate = self.temporary_root / f"{collision_kind}-candidate"
                planned_execution = candidate.with_name(
                    f".{candidate.name}.hffactory-planned-execution-{PROGRAM_ID}"
                )
                if collision_kind == "DIRECTORY":
                    planned_execution.mkdir()
                else:
                    planned_execution.symlink_to(
                        self.temporary_root / "missing-execution-root"
                    )

                with self.assertRaisesRegex(ValueError, "identity already exists"):
                    compile_start_package(
                        self.snapshot["requirement_ir"],
                        spec_root=ROOT.parent
                        / "Harness_Foundry_v2_8_Start_Package",
                        staging_root=staging,
                        candidate_root=candidate,
                        created_at="2026-08-12T00:00:00Z",
                        spec_lock={"content_sha256": "fixture", "files": {}},
                        authority_provenance={},
                        generation_readiness=self._evaluate(),
                    )

                self.assertFalse(staging.exists())
                self.assertFalse(candidate.exists())

    def test_real_compiler_packages_epoch38_runtime_store_dependency_closure(self) -> None:
        staging = self.temporary_root / "runtime-store-closure-staging"
        candidate = self.temporary_root / "runtime-store-closure-candidate"

        class RuntimeStoreClosureObserved(RuntimeError):
            pass

        def observe_validator(root: Path, **_kwargs: object) -> dict:
            runtime_root = root / "tools/harness_foundry_runtime"
            self.assertEqual(
                {path.name for path in runtime_root.glob("*.py")},
                {
                    "__init__.py",
                    "constants.py",
                    "control_kernel.py",
                    "local_runtime.py",
                    "local_process.py",
                    "startup_runtime.py",
                    "models.py",
                    "store.py",
                    "lab_protocol.py",
                    "lab_protocol_checks.py",
                },
            )
            for filename in (
                "constants.py",
                "control_kernel.py",
                "local_runtime.py",
                "local_process.py",
                "startup_runtime.py",
                "models.py",
                "store.py",
                "lab_protocol.py",
                "lab_protocol_checks.py",
            ):
                self.assertEqual(
                    (runtime_root / filename).read_bytes(),
                    (ROOT / "src/harness_foundry_factory" / filename).read_bytes(),
                )
            portable_files = json.loads(
                (root / "validation/PORTABLE_FILE_MANIFEST.json").read_text()
            )
            inventory = set(portable_files["files"]) | set(
                portable_files["excluded_files"]
            )
            self.assertEqual(
                _check_portable_runtime_dependency_closure(root, inventory),
                [],
            )
            self.assertEqual(
                _check_candidate_resource_uri_closure(root, inventory),
                [],
            )
            raise RuntimeStoreClosureObserved

        with patch(
            "harness_foundry_factory.validator.validate_candidate",
            side_effect=observe_validator,
        ):
            with self.assertRaises(RuntimeStoreClosureObserved):
                compile_start_package(
                    self.snapshot["requirement_ir"],
                    spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                    staging_root=staging,
                    candidate_root=candidate,
                    created_at="2026-08-12T00:00:00Z",
                    spec_lock={"content_sha256": "fixture", "files": {}},
                    authority_provenance={},
                    generation_readiness=self._evaluate(),
                )

        self.assertTrue(staging.is_dir())
        self.assertFalse(candidate.exists())

    def test_real_compiler_routes_epoch38_local_receipt_before_publication(self) -> None:
        staging = self.temporary_root / "local-receipt-routing-staging"
        candidate = self.temporary_root / "local-receipt-routing-candidate"
        bound_execution = self.temporary_root / "local-receipt-runtime-binding"
        planned_execution = candidate.with_name(
            f".{candidate.name}.hffactory-planned-execution-{PROGRAM_ID}"
        )

        initial_pass = {
            "status": "PASS",
            "validator_id": "HARNESS_FOUNDRY_FACTORY_VALIDATOR",
            "checks": [
                {
                    "check_id": "FACTORY_LOCAL_SOURCE_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                    "validation_basis": (
                        "FACTORY_SUPPLIED_LOCAL_CONSISTENCY_INPUT"
                    ),
                },
                {
                    "check_id": "FACTORY_LOCAL_REQUIREMENT_IR_CONSISTENCY",
                    "status": "PASS",
                    "findings": [],
                    "validation_basis": (
                        "FACTORY_SUPPLIED_LOCAL_CONSISTENCY_INPUT"
                    ),
                },
            ],
            "blocking_findings": [],
            "commands_executed": [],
        }

        class LocalReceiptObserved(RuntimeError):
            pass

        def observe_final_validator(root: Path, **_kwargs: object) -> dict:
            self.assertFalse(candidate.exists())
            self.assertFalse(planned_execution.exists())
            self.assertEqual(
                _check_epoch38_local_validation_report_receipt(root), []
            )
            receipt_path = (
                root / "validation/START_PACKAGE_VALIDATION_REPORT_RECEIPT.json"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["receipt_id"],
                "EPOCH38_LOCAL_VALIDATION_REPORT_RECEIPT",
            )
            self.assertFalse(receipt["external_authority_provenance_required"])
            self.assertFalse(receipt["external_certification_claimed"])
            self.assertFalse(receipt["independent_certification_claimed"])
            self.assertEqual(receipt["optional_security_hardening"], "NOT_RUN")
            self.assertFalse(receipt["closure_claimed"])
            self.assertFalse(receipt["human_review_approved"])
            self.assertNotIn("authority_provenance", receipt)
            self.assertNotIn("external_authority_checks_sha256", receipt)

            self_check = subprocess.run(
                [sys.executable, "tools/self_check.py"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(self_check.returncode, 0, self_check.stdout)
            self.assertEqual(json.loads(self_check.stdout)["status"], "PASS")

            runtime_bind = subprocess.run(
                [
                    sys.executable,
                    "tools/setup_runtime.py",
                    "--execution-root",
                    str(bound_execution),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(runtime_bind.returncode, 0, runtime_bind.stdout)
            binding_result = json.loads(runtime_bind.stdout)
            self.assertEqual(binding_result["status"], "PASS")
            binding_path = (
                bound_execution / ".harness-foundry/runtime_binding.json"
            )
            self.assertTrue(binding_path.is_file())
            binding_receipt = json.loads(binding_path.read_text(encoding="utf-8"))
            self.assertFalse(binding_receipt["candidate_write_performed"])

            self_check_module = runpy.run_path(str(root / "tools/self_check.py"))
            check_closure_receipt = self_check_module["check_closure_receipt"]
            frozen_ir = json.loads(
                (root / "canonical_sources/FROZEN_REQUIREMENT_IR.json").read_text(
                    encoding="utf-8"
                )
            )
            provenance = json.loads(
                (root / "FACTORY_PROVENANCE.json").read_text(encoding="utf-8")
            )
            matrix = json.loads(
                (
                    root / "validation/DAG_PATH_CONTAINMENT_MATRIX.json"
                ).read_text(encoding="utf-8")
            )
            package_identity = json.loads(
                (root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8")
            )
            closure_receipt = json.loads(
                (
                    root / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
                ).read_text(encoding="utf-8")
            )
            for field, value in (
                ("status", "PASS"),
                ("closure_claimed", True),
                ("human_review_approved", True),
            ):
                negative_receipt = deepcopy(closure_receipt)
                negative_receipt[field] = value
                self.assertIn(
                    "HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID",
                    {
                        finding["code"]
                        for finding in check_closure_receipt(
                            root,
                            frozen_ir,
                            provenance,
                            matrix,
                            negative_receipt,
                            package_identity,
                        )
                    },
                )

            forged_claim = deepcopy(receipt)
            forged_claim["external_certification_claimed"] = True
            forged_claim["receipt_sha256"] = _rehash(
                forged_claim, "receipt_sha256"
            )
            receipt_path.write_text(
                json.dumps(forged_claim), encoding="utf-8"
            )
            self.assertEqual(
                {
                    item["code"]
                    for item in _check_epoch38_local_validation_report_receipt(
                        root
                    )
                },
                {"EPOCH38_LOCAL_VALIDATION_RECEIPT_INVALID"},
            )

            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            closure_path = root / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
            closure = json.loads(closure_path.read_text(encoding="utf-8"))
            closure["status"] = "PASS"
            closure_path.write_text(json.dumps(closure), encoding="utf-8")
            self.assertEqual(
                {
                    item["code"]
                    for item in _check_epoch38_local_validation_report_receipt(
                        root
                    )
                },
                {"EPOCH38_LOCAL_VALIDATION_RECEIPT_INVALID"},
            )
            raise LocalReceiptObserved

        with patch(
            "harness_foundry_factory.validator.validate_candidate",
            return_value=initial_pass,
        ), patch(
            "harness_foundry_factory.validator."
            "_validate_prepublication_staging_candidate",
            side_effect=observe_final_validator,
        ):
            with self.assertRaises(LocalReceiptObserved):
                compile_start_package(
                    self.snapshot["requirement_ir"],
                    spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                    staging_root=staging,
                    candidate_root=candidate,
                    created_at="2026-08-12T00:00:00Z",
                    spec_lock={"content_sha256": "fixture", "files": {}},
                    authority_provenance={},
                    generation_readiness=self._evaluate(),
                )

        self.assertTrue(staging.is_dir())
        self.assertFalse(candidate.exists())
        self.assertFalse(planned_execution.exists())
        self.assertTrue(bound_execution.is_dir())

    def test_epoch4_route_projection_excludes_optional_security_from_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = {
                "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
            }
            (root / "EPOCH38_GENERATION_PROFILE.json").write_text(
                json.dumps(profile), encoding="utf-8"
            )
            (root / "ENGINEERING_PROJECT_DAG.json").write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"node_id": "MAIN_G0_C0"},
                            {"node_id": "LAB_BOOTSTRAP"},
                            {"node_id": "LINKAGE_BOOTSTRAP"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "RELEASE_PIPELINE_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "steps": [
                            {"step_id": "P4_RELEASE_CANDIDATE_LOCK"},
                            {"step_id": "P4_CERTIFIED_RELEASE_LOCK"},
                            {
                                "step_id":
                                "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS"
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "THREE_PROJECT_PROGRAM_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "projects": [
                            {"project_id": "MAIN_HARNESS_BUILD"},
                            {"project_id": "EXTERNAL_CONFORMANCE_LAB"},
                            {"project_id": "CONFORMANCE_LINKAGE_REVIEW"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            main = root / "project_start_packages" / "main_build"
            main.mkdir(parents=True)
            (main / "WORKPACK_INDEX.json").write_text(
                json.dumps(
                    {
                        "workpacks": [
                            {"workpack_id": "MB-G0"},
                            {"workpack_id": "MB-RELEASE-CANDIDATE"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            _apply_epoch4_default_route_selection(root)

            projects = json.loads(
                (root / "THREE_PROJECT_PROGRAM_MANIFEST.json").read_text()
            )
            release = json.loads(
                (root / "RELEASE_PIPELINE_MANIFEST.json").read_text()
            )
            self.assertEqual(
                projects["default_route_project_ids"], ["MAIN_HARNESS_BUILD"]
            )
            self.assertTrue(projects["projects"][0]["default_route_selected"])
            self.assertTrue(
                all(
                    not item["default_route_selected"]
                    and item["delivery_tier"] == "OPTIONAL_SECURITY_HARDENING"
                    and item["default_profile_disposition"]
                    == "NOT_APPLICABLE_NOT_STARTED"
                    for item in projects["projects"][1:]
                )
            )
            self.assertEqual(
                [
                    item["step_id"]
                    for item in release["steps"]
                    if item["default_route_selected"]
                ],
                ["P4_RELEASE_CANDIDATE_LOCK"],
            )
            dag = json.loads((root / "ENGINEERING_PROJECT_DAG.json").read_text())
            self.assertEqual(dag["default_route_edges"], [])
            main_index = json.loads((main / "WORKPACK_INDEX.json").read_text())
            release_workpack = next(
                item
                for item in main_index["workpacks"]
                if item["workpack_id"] == "MB-RELEASE-CANDIDATE"
            )
            self.assertEqual(
                release_workpack["default_profile_requires"],
                [
                    "P4_LOCAL_GATE_PASS",
                    "OFFICIAL_CORE_VALIDATION_PASS",
                    "CORE_EVIDENCE_PROJECTION_PASS",
                ],
            )

    def test_real_compiler_closes_epoch38_default_route_capabilities(self) -> None:
        staging = self.temporary_root / "default-route-closure-staging"
        candidate = self.temporary_root / "default-route-closure-candidate"

        class DefaultRouteClosureObserved(RuntimeError):
            pass

        def observe_validator(root: Path, **_kwargs: object) -> dict:
            self.assertEqual(_check_epoch38_generation_route(root), [])
            validation = run_candidate_validation(
                root,
                expected_target_root=candidate,
            )
            route_contract_codes = {
                "EPOCH38_DEFAULT_ROUTE_CAPABILITY_LEAK",
                "EPOCH38_DEFAULT_ROUTE_NOT_INDEPENDENT",
                "ENGINEERING_DAG_NODE_CONTRACT_INCOMPLETE",
                "ENGINEERING_WORKPACK_BINDING_INVALID",
                "ROOT_MATERIALIZATION_WORKPACK_INVALID",
                "ROOT_MATERIALIZATION_CAPABILITY_INVALID",
                "RELEASE_WORKPACK_BINDING_INVALID",
                "PROJECT_WORKPACK_EXECUTION_CONTRACT_INVALID",
                "PROJECT_WORKPACK_CAPSULE_INVALID",
                "PROJECT_WORKPACK_RESULT_INVALID",
                "RELEASE_STEP_INVALID",
            }
            self.assertTrue(
                route_contract_codes.isdisjoint(
                    {
                        item["code"]
                        for item in validation.get("blocking_findings", [])
                    }
                ),
                validation.get("blocking_findings"),
            )
            dag = json.loads(
                (root / "ENGINEERING_PROJECT_DAG.json").read_text()
            )
            self.assertEqual(
                dag["active_route_edge_field"], "default_route_edges"
            )
            self.assertEqual(
                dag["edges_role"],
                "COMPATIBILITY_CATALOG_NOT_ACTIVE_DEFAULT_EXECUTION_ROUTE",
            )
            self.assertEqual(dag["compatibility_catalog_edges"], dag["edges"])
            compatibility_only_progressions = {
                "MAIN_EXECUTION_BEFORE_LAB_AND_LINKAGE_SELF_VALIDATION",
                "MAIN_EXECUTION_PACKAGE_BEFORE_LAB_AND_LINKAGE_RELEASE",
            }
            self.assertTrue(
                compatibility_only_progressions.isdisjoint(
                    dag["forbidden_progressions"]
                )
            )
            self.assertEqual(
                set(dag["optional_security_forbidden_progressions"]),
                compatibility_only_progressions,
            )
            optional_nodes = set(dag["optional_security_node_ids"])
            self.assertTrue(optional_nodes)
            for node in dag["nodes"]:
                if node.get("default_route_selected") is not True:
                    continue
                operational_refs = {
                    *node.get("required_predecessor_nodes", []),
                    *node.get("requires", []),
                    *node.get("allowed_next_nodes", []),
                    node.get("failure_return_node"),
                }
                self.assertTrue(operational_refs.isdisjoint(optional_nodes))
                self.assertEqual(
                    node["required_tool_distribution_hashes"],
                    {"status": "NOT_APPLICABLE_SELF_USE_LOCAL"},
                )

            root_index = json.loads(
                (root / "WORKPACK_INDEX.json").read_text()
            )
            root_workpack = root_index["workpacks"][0]
            root_capsule = json.loads((root / "CAPSULE.json").read_text())
            expected_root = ["CHARTER_LOCK_VALID", "PROFILE_LOCK_VALID"]
            self.assertEqual(root_workpack["requires"], expected_root)
            self.assertEqual(root_capsule["requires"], expected_root)

            release = json.loads(
                (root / "RELEASE_PIPELINE_MANIFEST.json").read_text()
            )
            default_release = next(
                item for item in release["steps"]
                if item.get("default_route_selected") is True
            )
            expected_release = [
                "P4_LOCAL_GATE_PASS",
                "OFFICIAL_CORE_VALIDATION_PASS",
                "CORE_EVIDENCE_PROJECTION_PASS",
            ]
            self.assertEqual(default_release["requires"], expected_release)
            self.assertEqual(default_release["required_predecessor_step_ids"], [])
            self.assertEqual(default_release["allowed_next_step_ids"], [])

            main_root = root / "project_start_packages/main_build"
            main_index = json.loads(
                (main_root / "WORKPACK_INDEX.json").read_text()
            )
            release_workpack = next(
                item for item in main_index["workpacks"]
                if item["workpack_id"] == "MB-RELEASE-CANDIDATE"
            )
            release_capsule = json.loads(
                (
                    main_root
                    / "capsules/MB-RELEASE-CANDIDATE.capsule.json"
                ).read_text()
            )
            release_result = json.loads(
                (
                    main_root
                    / "results/MB-RELEASE-CANDIDATE.result.json"
                ).read_text()
            )
            self.assertEqual(release_workpack["requires"], expected_release)
            self.assertEqual(release_capsule["requires"], expected_release)
            self.assertEqual(
                release_result["required_capabilities"], expected_release
            )

            # The active local route must fail closed if a legacy optional-
            # security blocker is projected back into its progression rules.
            dag["forbidden_progressions"].append(
                "MAIN_EXECUTION_BEFORE_LAB_AND_LINKAGE_SELF_VALIDATION"
            )
            (root / "ENGINEERING_PROJECT_DAG.json").write_text(
                json.dumps(dag), encoding="utf-8"
            )
            self.assertIn(
                "EPOCH38_DEFAULT_ROUTE_FORBIDDEN_PROGRESSION_LEAK",
                {
                    item["code"]
                    for item in _check_epoch38_generation_route(root)
                },
            )

            # A non-executable JSON negative fixture proves the Validator closes
            # the exact regression instead of trusting the projected route flag.
            root_workpack["requires"] = ["LINKAGE_TOOL_RELEASE_LOCK_VALID"]
            (root / "WORKPACK_INDEX.json").write_text(
                json.dumps(root_index),
                encoding="utf-8",
            )
            self.assertIn(
                "EPOCH38_DEFAULT_ROUTE_CAPABILITY_LEAK",
                {
                    item["code"]
                    for item in _check_epoch38_generation_route(root)
                },
            )
            raise DefaultRouteClosureObserved

        with patch(
            "harness_foundry_factory.validator.validate_candidate",
            side_effect=observe_validator,
        ):
            with self.assertRaises(DefaultRouteClosureObserved):
                compile_start_package(
                    self.snapshot["requirement_ir"],
                    spec_root=ROOT.parent / "Harness_Foundry_v2_8_Start_Package",
                    staging_root=staging,
                    candidate_root=candidate,
                    created_at="2026-08-12T00:00:00Z",
                    spec_lock={"content_sha256": "fixture", "files": {}},
                    authority_provenance={},
                    generation_readiness=self._evaluate(),
                )

        self.assertTrue(staging.is_dir())
        self.assertFalse(candidate.exists())


def _epoch38_fixture(
    candidate_root: Path,
    *,
    active_requirement_epoch: int = 38,
    include_active_requirement_marker: bool = True,
    include_shared_control_baseline: bool = False,
    program_id: str = PROGRAM_ID,
    target_id: str = "SLICE09-FIXTURE",
) -> dict:
    tiers = {
        **{
            f"ATOM-V29-P0-{number:02d}": "CORE_IMPLEMENTATION"
            for number in (*range(1, 8), 10)
        },
        "ATOM-V29-P0-08": "POST_IMPLEMENTATION_VALIDATION",
        "ATOM-V29-P0-09": "OPTIONAL_SECURITY_HARDENING",
    }
    routing = {
        1: (["MB-G0"], ["G0"], []),
        2: (["MB-P1"], ["P1"], []),
        3: (["MB-P1"], ["C1"], []),
        4: (["MB-P2"], ["P2"], []),
        5: (["MB-P2"], ["C2"], []),
        6: (["MB-P3"], ["P3"], []),
        7: (["MB-P3"], ["C3"], []),
        8: (
            ["MB-RELEASE-CANDIDATE"],
            ["RELEASE_PIPELINE"],
            ["P4_RELEASE_CANDIDATE_LOCK"],
        ),
        9: (
            [
                "LINK-PROTOCOL",
                "LINK-CLI",
                "LINK-SELFTEST",
                "LINK-PREFLIGHT",
                "LINK-D",
            ],
            ["RELEASE_PIPELINE"],
            [
                "LINKAGE_A_INTERFACE_COMPLETENESS",
                "LINKAGE_D_INSTALLED_HANDSHAKE",
            ],
        ),
        10: (
            ["MB-P4", "MB-RELEASE-CANDIDATE"],
            ["P4_BUILD_INPUT", "RELEASE_PIPELINE"],
            ["P4_RELEASE_CANDIDATE_LOCK"],
        ),
    }
    project_by_workpack = {
        **{item: "MAIN_HARNESS_BUILD" for item in CORE_ROUTES},
        **{
            item: "CONFORMANCE_LINKAGE_REVIEW"
            for item in OPTIONAL_SECURITY_ROUTES
            if item.startswith("LINK-")
        },
        **{
            item: "EXTERNAL_CONFORMANCE_LAB"
            for item in OPTIONAL_SECURITY_ROUTES
            if item.startswith("LAB-")
        },
    }
    atoms = []
    coverage_edges = []
    for number in range(1, 11):
        atom_id = f"ATOM-V29-P0-{number:02d}"
        workpacks, stages, release_steps = routing[number]
        atoms.append(
            {
                "atom_id": atom_id,
                "source_id": "SRC-SLICE09-FIXTURE",
                "source_locator": f"fixture#{number}",
                "text_or_lossless_paraphrase": f"Slice 09 fixture Atom {number}",
                "modality": "MUST",
                "owner": sorted({project_by_workpack[item] for item in workpacks})[0],
                "verification_mode": "CORE_REGRESSION",
                "delivery_tier": tiers[atom_id],
            }
        )
        coverage_edges.append(
            {
                "atom_id": atom_id,
                "workpack_ids": workpacks,
                "stage_ids": stages,
                "release_step_ids": release_steps,
                "owner_project_ids": sorted(
                    {project_by_workpack[item] for item in workpacks}
                ),
                "routing_basis": "EXPLICIT_EPOCH38_FIXTURE",
                "status": "PLANNED_NOT_VERIFIED",
            }
        )

    ir = {
        "program_id": program_id,
        "target": {
            "id": target_id,
            "name": "Slice 09 self-contained fixture",
            "type": "HARNESS",
            "profile": "FULL",
            "output_root": str(candidate_root),
            "mission": "Validate the Epoch 38 prewrite gate without Program state.",
            "scope": [
                f"P0-{number:02d} Slice 09 fixture capability {number}"
                for number in range(1, 11)
            ],
            "non_goals": ["Generate or execute a Candidate"],
            "primary_runtime": "Codex",
            "portability_mode": "LOGICAL_RESOURCE_URI",
            "requirement_epoch": 38,
            "architecture_epoch": 4,
            "control_plane_epoch": 4,
            "assurance_profile_id": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
            "operating_assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
            "delivery_priority_mode": "IMPLEMENTATION_PRIORITY_TIERED_ASSURANCE",
            "epoch4_architecture_control_plane_contract": {
                "contract_status": "NORMATIVE_REQUIREMENT",
                "requirement_epoch": 38,
                "architecture_epoch": 4,
                "control_plane_epoch": 4,
                "assurance_profile_id": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
                "unsupported_or_mixed_route_result": "FAIL_BEFORE_CANDIDATE_WRITE",
            },
            "v2_9_charter_architecture_correction_epoch38": {
                "mission": (
                    "Implement usable local v2.9 engineering capability first; "
                    "validation proves implemented behavior and cannot replace "
                    "implementation."
                ),
                "active_delivery_route_projection": {
                    "core_routes": CORE_ROUTES,
                    "optional_security_routes": OPTIONAL_SECURITY_ROUTES,
                    "default_generation_release_steps": [
                        "P4_RELEASE_CANDIDATE_LOCK"
                    ],
                    "excluded_default_release_steps": EXCLUDED_RELEASE_STEPS,
                    "post_implementation_validation_route": [
                        "MB-RELEASE-CANDIDATE"
                    ],
                },
                "claim_vocabulary": {
                    "local_engineering_completion": "CORE_RELEASE_READY_LOCAL",
                    "external_certification": "NOT_CLAIMED",
                    "optional_security_hardening": "NOT_RUN_OR_NOT_APPLICABLE",
                },
                "threat_model": {
                    "external_trust_anchor": "NOT_APPLICABLE",
                    "independent_control_domain": "NOT_APPLICABLE",
                    "dynamic_adversarial_reproduction": "NOT_APPLICABLE",
                    "external_certification_offered": False,
                    "accepts_third_party_candidate": False,
                },
                "atom_delivery_tiers": tiers,
            },
        },
        "sources": [
            {
                "source_id": "SRC-SLICE09-FIXTURE",
                "path_or_uri": "fixture://slice09",
                "sha256": "0" * 64,
                "authority_level": "HUMAN_PROVIDED",
                "scope": "Slice 09 non-executing regression fixture",
                "loaded_completely": True,
            }
        ],
        "atoms": atoms,
        "coverage_edges": coverage_edges,
        "acceptance_cases": [
            {
                "case_id": "AC-SLICE09",
                "atom_ids": ["ATOM-V29-P0-01"],
                "description": "Valid Hash-bound local profile is ready.",
                "evidence_type": "STATIC_GATE_RESULT",
            }
        ],
        "negative_cases": [
            {
                "case_id": "NEG-SLICE09",
                "atom_ids": ["ATOM-V29-P0-09"],
                "description": "Optional security cannot enter the default route.",
                "expected_failure": "GENERATION_SECURITY_BOUNDARY_INVALID",
            }
        ],
        "open_questions": [],
        "source_conflicts": [],
        "automation": {"max_transitions": 8, "max_loop_rounds": 2},
    }
    if active_requirement_epoch >= 45 and include_active_requirement_marker:
        ir["target"]["epoch45_controlled_runtime_workpack_closure"] = {
            "active_epochs": {
                "requirement_epoch": active_requirement_epoch,
                "architecture_epoch": 4,
                "control_plane_epoch": 4,
            },
            "node_id": "MAIN_EXECUTION_PACKAGE_MATERIALIZED",
            "workpack_id": "WP-HARNESS-FOUNDRY-V2-9-CHAT-FACTORY-G0-001",
        }
    if include_shared_control_baseline:
        fixture = json.loads(
            (ROOT / "tests/fixtures/shared_control_baseline_contract.json").read_text(
                encoding="utf-8"
            )
        )
        ir["target"].update(
            {
                "shared_control_baseline_execution_contract": fixture[
                    "execution_contract"
                ],
                "shared_control_baseline_test_contract": fixture["test_contract"],
            }
        )
    ir_sha256 = content_sha256(ir)
    requirement_lock = {
        "schema_version": "2.9",
        "status": "LOCKED",
        "requirement_epoch": active_requirement_epoch,
        "requirement_ir_sha256": ir_sha256,
    }
    requirement_lock["requirement_lock_sha256"] = content_sha256(requirement_lock)
    architecture_readback = {
        "schema_version": "2.9",
        "program_id": program_id,
        "requirement_epoch": active_requirement_epoch,
        "architecture_epoch": 4,
        "control_plane_epoch": 4,
        "capabilities": [{"capability_id": "PROFILE_AWARE_PREFLIGHT"}],
        "stages": [{"stage_id": "PREWRITE_READINESS"}],
        "subharnesses": [],
        "modules": [{"module_id": "generation_readiness"}],
        "rules": [{"rule_id": "FAIL_BEFORE_WRITE"}],
        "policies": [{"policy_id": "SELF_USE_LOCAL_DEFAULT_ROUTE"}],
        "tools": [],
        "interfaces": [{"interface_id": "FactoryService.generation_readiness"}],
        "failure_returns": [
            {"code": "GENERATION_SECURITY_BOUNDARY_INVALID", "owner": "AUTHOR"}
        ],
        "unresolved_decisions": [],
    }
    architecture_readback_sha256 = content_sha256(architecture_readback)
    topology = {
        field: architecture_readback[field]
        for field in (
            "capabilities",
            "stages",
            "subharnesses",
            "modules",
            "rules",
            "policies",
            "tools",
            "interfaces",
        )
    }
    architecture_lock = {
        "schema_version": "2.9",
        "status": "LOCKED",
        "requirement_epoch": active_requirement_epoch,
        "architecture_epoch": 4,
        "control_plane_epoch": 4,
        "requirement_lock_sha256": requirement_lock["requirement_lock_sha256"],
        "architecture_readback_sha256": architecture_readback_sha256,
        "topology_sha256": content_sha256(topology),
        "failure_return_map_sha256": content_sha256(
            architecture_readback["failure_returns"]
        ),
    }
    architecture_lock["architecture_lock_sha256"] = content_sha256(
        architecture_lock
    )
    compiled_contract = compile_requirement_architecture_contract(
        ir,
        requirement_lock=requirement_lock,
        architecture_readback=architecture_readback,
        architecture_lock=architecture_lock,
    )
    snapshot = {
        "program_id": program_id,
        "factory_state": "REQUIREMENTS_FROZEN",
        "requirement_epoch": active_requirement_epoch,
        "requirement_ir": ir,
        "freeze": {
            "status": "FROZEN",
            "requirement_epoch": active_requirement_epoch,
            "requirement_ir_sha256": ir_sha256,
        },
    }
    return {
        "snapshot": snapshot,
        "requirement_lock": requirement_lock,
        "architecture_readback": architecture_readback,
        "architecture_lock": architecture_lock,
        "compiled_contract": compiled_contract,
    }


def _rehash(value: dict, field: str) -> str:
    material = deepcopy(value)
    material.pop(field, None)
    return content_sha256(material)


if __name__ == "__main__":
    unittest.main()
