"""Candidate integration checks for the Epoch 9 generic control plane."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.validator import validate_candidate
from tests.permissions import make_path_writable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPOSITORY_ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURE_PATH = REPOSITORY_ROOT / "tests/fixtures/harness_requirement_ir.json"
CORRECTION_IDS = [f"CORR-29-{index:03d}" for index in range(1, 9)]


def json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def write_json(path: Path, value: object) -> None:
    make_path_writable(path)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class ControlKernelCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.candidate = self.root / "candidate"
        self.ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.ir["target"].update(
            {
                "output_root": str(self.candidate),
                "execution_root": str(self.root / "execution"),
                "portability_mode": "LOGICAL_RESOURCE_URI",
                "architecture_epoch": 1,
                "control_plane_epoch": 1,
                "assurance_profile_id": "V29_CONTROL_PLANE_CORRECTION_AUTHORING",
                "shared_control_baseline_fixture_role": (
                    "HISTORICAL_GOLDEN_FIXTURE_ONLY_NO_SUCCESSOR_AUTHORITY"
                ),
                "control_plane_architecture_correction": {
                    "status": "FROZEN",
                    "architecture_lock_proposal_sha256": "a" * 64,
                    "correction_requirements": [
                        {
                            "correction_id": correction_id,
                            "maps_to": [
                                "ATOM-001" if index % 2 else "ATOM-002"
                            ],
                            "requirement": f"Frozen correction {correction_id}",
                        }
                        for index, correction_id in enumerate(CORRECTION_IDS, 1)
                    ],
                    "correction_traceability": {
                        "candidate_artifact_ref": (
                            "canonical_sources/CORRECTION_COVERAGE_MATRIX.json"
                        ),
                        "expected_correction_ids": CORRECTION_IDS,
                        "mapping_source": (
                            "target.control_plane_architecture_correction."
                            "correction_requirements"
                        ),
                        "required": True,
                        "runtime_evidence_must_remain_pending_until_execution": True,
                        "standalone_self_check_required": True,
                        "validator_mode": (
                            "FAIL_CLOSED_EXACT_MAPPING_AND_HASH_BINDING"
                        ),
                    },
                },
                "human_review_v0_10_closure": {
                    "finding_ids": [
                        "FINDING-V0-10-CORR-TRACEABILITY-001",
                        "FINDING-V0-10-STANDALONE-CONTROL-KERNEL-SEMANTIC-CHECK-001",
                    ],
                    "replacement_candidate": "candidate",
                    "required_closures": [
                        "Exact CORR coverage",
                        "Independent standalone control-kernel self-check",
                    ],
                    "runtime_claims_verified": False,
                    "status": (
                        "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
                    ),
                    "superseded_candidate": "candidate-v0_10",
                    "workpack_execution_authorized": False,
                },
                "v0_11_execution_integration_correction": {
                    "correction_ids": [
                        "V011-CORR-DETERMINISTIC-FAILURE-001",
                        "V011-CORR-NATIVE-CONTROL-STORE-002",
                    ],
                    "adapter_binding_contract": {
                        "candidate_artifact_ref": (
                            "PROFILE_READ_VALIDATION_ADAPTER_BINDING.json"
                        ),
                        "initial_status": "PLANNED_NOT_BOUND",
                        "schema_ref": "contracts/v2_9/ADAPTER_BINDING.schema.json",
                    },
                    "native_control_event_store_activation_contract": {
                        "candidate_artifact_ref": (
                            "CONTROL_EVENT_STORE_ACTIVATION_CONTRACT.json"
                        ),
                        "active_store_ref": (
                            "harness-resource://execution/.harness-foundry/"
                            "control/v2_9/control_event_store.sqlite3"
                        ),
                        "historical_v0_11_event_hash": "5" * 64,
                    },
                },
                "human_review_v0_11_closure": {
                    "finding_ids": [
                        "FINDING-V0-11-READ-VALIDATION-DETERMINISTIC-FAILURE-STATE-001",
                        "FINDING-EXECUTION-V0-4-BOOTSTRAP-STORE-SCHEMA-INCOMPATIBLE-001",
                    ],
                    "replacement_candidate": "candidate",
                    "required_closures": [
                        "Deterministic validation failure is a non-retry stop",
                        "Native Event Store activation contract is exact",
                    ],
                    "runtime_claims_verified": False,
                    "status": (
                        "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
                    ),
                    "superseded_candidate": "candidate-v0_11",
                    "workpack_execution_authorized": False,
                },
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def compile(self) -> None:
        compile_candidate(
            deepcopy(self.ir),
            SPEC_ROOT,
            self.root / "staging",
            self.candidate,
            "2026-08-04T09:00:00Z",
        )

    def finding_codes(self) -> set[str]:
        report = validate_candidate(self.candidate)
        return {
            finding["code"]
            for check in report["checks"]
            for finding in check["findings"]
        }

    def run_self_check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "tools/self_check.py"],
            cwd=self.candidate,
            check=False,
            capture_output=True,
            text=True,
        )

    def refresh_closure_and_portable_hashes(self) -> None:
        receipt_path = (
            self.candidate / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        for closure in receipt["closures"]:
            closure["evidence_sha256"] = {
                relative: hashlib.sha256(
                    (self.candidate / relative).read_bytes()
                ).hexdigest()
                for relative in closure["evidence_refs"]
            }
        write_json(receipt_path, receipt)

        portable_path = self.candidate / "validation/PORTABLE_FILE_MANIFEST.json"
        portable = json.loads(portable_path.read_text(encoding="utf-8"))
        excluded = set(portable["excluded_files"])
        files = {
            path.relative_to(self.candidate).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(self.candidate.rglob("*"))
            if path.is_file()
            and path.relative_to(self.candidate).as_posix() not in excluded
        }
        portable["file_count"] = len(files)
        portable["files"] = files
        write_json(portable_path, portable)

    def test_corrected_candidate_packages_active_generic_kernel(self) -> None:
        self.compile()
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        manifest = json.loads(
            (self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        portable = json.loads((self.candidate / "validation/PORTABLE_FILE_MANIFEST.json").read_text())
        for filename in ("lab_protocol.py", "lab_protocol_checks.py"):
            ref = "tools/harness_foundry_runtime/" + filename
            self.assertTrue((self.candidate / ref).is_file())
            self.assertIn(ref, portable["files"])
            self.assertNotIn(ref, manifest["runtime_module_sha256"])
        graph = json.loads(
            (self.candidate / "CONTROL_PLANE_PROGRAM_GRAPH.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["parent_authorization_status"], "NOT_GRANTED")
        self.assertFalse(manifest["execution_started"])
        self.assertEqual(
            manifest["control_event_store_activation_status"],
            "PLANNED_NOT_ACTIVATED",
        )
        result_schema = json.loads(
            (
                self.candidate
                / "contracts/v2_9/TRANSITION_RESULT.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(
            "VALIDATION_FAILED",
            result_schema["properties"]["status"]["enum"],
        )
        adapter = json.loads(
            (
                self.candidate
                / "PROFILE_READ_VALIDATION_ADAPTER_BINDING.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(adapter["binding_status"], "PLANNED_NOT_BOUND")
        self.assertIsNone(adapter["implementation_sha256"])
        activation = json.loads(
            (
                self.candidate
                / "CONTROL_EVENT_STORE_ACTIVATION_CONTRACT.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(activation["store_created"])
        self.assertFalse(activation["store_migrated"])
        self.assertEqual(
            set(activation["native_schema_contract"]["append_only_triggers"]),
            {"control_events_reject_update", "control_events_reject_delete"},
        )
        self.assertEqual(
            {node["node_kind"] for node in graph["nodes"]},
            {
                "READ_ONLY_VALIDATION",
                "INTERNAL_STATE_TRANSACTION",
                "BOUNDED_REVERSIBLE_FIXTURE_ACTION",
            },
        )
        self.assertFalse((self.candidate / "tools/shared_control_baseline.py").exists())
        legacy = json.loads(
            (self.candidate / "ENGINEERING_PROJECT_DAG.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(legacy["authority_role"], "V28_COMPATIBILITY_FIXTURE_ONLY")
        self.assertFalse(legacy["successor_execution_allowed"])
        correction = json.loads(
            (
                self.candidate
                / "canonical_sources/CORRECTION_COVERAGE_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(correction["expected_correction_ids"], CORRECTION_IDS)
        self.assertEqual(correction["correction_count"], 8)
        self.assertEqual(correction["candidate_static_status"], "PASS")
        self.assertEqual(
            correction["runtime_evidence_status"],
            "PENDING_UNTIL_AUTHORIZED_EXECUTION",
        )
        receipt = json.loads(
            (
                self.candidate
                / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
            ).read_text(encoding="utf-8")
        )
        closure = next(
            item
            for item in receipt["closures"]
            if item["requirement_key"] == "human_review_v0_10_closure"
        )
        self.assertIn(
            "canonical_sources/CORRECTION_COVERAGE_MATRIX.json",
            closure["evidence_refs"],
        )
        self.assertIn("tools/self_check.py", closure["evidence_refs"])
        closure_v0_11 = next(
            item
            for item in receipt["closures"]
            if item["requirement_key"] == "human_review_v0_11_closure"
        )
        self.assertIn(
            "CONTROL_EVENT_STORE_ACTIVATION_CONTRACT.json",
            closure_v0_11["evidence_refs"],
        )
        self.assertIn(
            "contracts/v2_9/TRANSITION_RESULT.schema.json",
            closure_v0_11["evidence_refs"],
        )
        self.assertEqual(self.run_self_check().returncode, 0)
        readme = (self.candidate / "README.md").read_text(encoding="utf-8")
        self.assertIn("v2.9 Generic Control Kernel", readme)
        self.assertIn("PLANNED_NOT_BOUND", readme)

    def test_generic_kernel_manifest_tamper_is_rejected(self) -> None:
        self.compile()
        manifest_path = self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json"
        make_path_writable(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["runtime_module_sha256"][
            "tools/harness_foundry_runtime/control_kernel.py"
        ] = "b" * 64
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.assertIn("V2_9_CONTROL_KERNEL_MANIFEST_INVALID", self.finding_codes())
        self.assertIn("V2_9_CONTROL_KERNEL_MODULE_HASH_INVALID", self.finding_codes())

    def test_control_manifest_rejects_missing_or_unrelated_owned_module_records(self) -> None:
        self.compile()
        path = self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json"
        original = json.loads(path.read_text())
        for mutation in ("missing", "unrelated"):
            with self.subTest(mutation=mutation):
                manifest = deepcopy(original)
                if mutation == "missing":
                    manifest["runtime_module_sha256"].pop("tools/harness_foundry_runtime/constants.py")
                else:
                    ref = "tools/harness_foundry_runtime/lab_protocol.py"
                    manifest["runtime_module_sha256"][ref] = hashlib.sha256((self.candidate / ref).read_bytes()).hexdigest()
                manifest["manifest_sha256"] = json_hash({key: value for key, value in manifest.items() if key != "manifest_sha256"})
                write_json(path, manifest)
                self.refresh_closure_and_portable_hashes()
                self.assertIn("V2_9_CONTROL_KERNEL_MODULE_HASH_INVALID", self.finding_codes())
                result = self.run_self_check()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("V2_9_CONTROL_KERNEL_MODULE_HASH_INVALID", result.stdout)

    def test_hash_consistent_correction_mapping_tamper_fails_both_oracles(
        self,
    ) -> None:
        self.compile()
        matrix_path = (
            self.candidate / "canonical_sources/CORRECTION_COVERAGE_MATRIX.json"
        )
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        atom_coverage = json.loads(
            (
                self.candidate / "canonical_sources/ATOM_COVERAGE_MATRIX.json"
            ).read_text(encoding="utf-8")
        )
        edge = next(
            item for item in atom_coverage["coverage"] if item["atom_id"] == "ATOM-002"
        )
        row = matrix["rows"][0]
        row["maps_to"] = ["ATOM-002"]
        row["mapped_atom_coverage"] = [
            {
                "atom_id": "ATOM-002",
                "workpack_ids": edge["workpack_ids"],
                "stage_ids": edge["stage_ids"],
                "release_step_ids": edge["release_step_ids"],
                "owner_project_ids": edge["owner_project_ids"],
                "coverage_status": edge["status"],
            }
        ]
        row["row_sha256"] = json_hash(
            {key: value for key, value in row.items() if key != "row_sha256"}
        )
        matrix["matrix_sha256"] = json_hash(
            {key: value for key, value in matrix.items() if key != "matrix_sha256"}
        )
        write_json(matrix_path, matrix)
        manifest_path = self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["correction_coverage_sha256"] = hashlib.sha256(
            matrix_path.read_bytes()
        ).hexdigest()
        manifest["manifest_sha256"] = json_hash(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()

        self.assertIn("V2_9_CORRECTION_COVERAGE_INVALID", self.finding_codes())
        result = self.run_self_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V2_9_CORRECTION_COVERAGE_INVALID", result.stdout)

    def test_hash_consistent_policy_semantic_tamper_fails_both_oracles(
        self,
    ) -> None:
        self.compile()
        policy_path = self.candidate / "DECISION_POLICY.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["unknown_policy"] = "ALLOW_UNKNOWN"
        write_json(policy_path, policy)
        policy_sha = hashlib.sha256(policy_path.read_bytes()).hexdigest()

        transitions_path = self.candidate / "TRANSITION_CONTRACTS.json"
        transitions = json.loads(transitions_path.read_text(encoding="utf-8"))
        for contract in transitions["contracts"]:
            contract["decision_policy_sha256"] = policy_sha
        transitions["contracts_sha256"] = json_hash(transitions["contracts"])
        write_json(transitions_path, transitions)

        manifest_path = self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["decision_policy_sha256"] = policy_sha
        manifest["transition_contracts_sha256"] = hashlib.sha256(
            transitions_path.read_bytes()
        ).hexdigest()
        manifest["manifest_sha256"] = json_hash(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()

        self.assertIn("V2_9_DECISION_POLICY_BINDING_INVALID", self.finding_codes())
        result = self.run_self_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V2_9_CONTROL_KERNEL_POLICY_INVALID", result.stdout)

    def test_hash_consistent_deterministic_failure_tamper_fails_both_oracles(
        self,
    ) -> None:
        self.compile()
        schema_path = (
            self.candidate / "contracts/v2_9/TRANSITION_RESULT.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["properties"]["status"]["enum"].remove("VALIDATION_FAILED")
        write_json(schema_path, schema)
        schema_sha = hashlib.sha256(schema_path.read_bytes()).hexdigest()

        adapter_path = (
            self.candidate / "PROFILE_READ_VALIDATION_ADAPTER_BINDING.json"
        )
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
        adapter["result_schema_sha256"] = schema_sha
        adapter["binding_contract_sha256"] = json_hash(
            {
                key: value
                for key, value in adapter.items()
                if key != "binding_contract_sha256"
            }
        )
        write_json(adapter_path, adapter)
        adapter_sha = hashlib.sha256(adapter_path.read_bytes()).hexdigest()

        transitions_path = self.candidate / "TRANSITION_CONTRACTS.json"
        transitions = json.loads(transitions_path.read_text(encoding="utf-8"))
        for contract in transitions["contracts"]:
            contract["result_schema_sha256"] = schema_sha
            if contract["transition_id"] == "PROFILE_READ_VALIDATION":
                contract["command_contract"]["adapter_binding_sha256"] = adapter_sha
        transitions["contracts_sha256"] = json_hash(transitions["contracts"])
        write_json(transitions_path, transitions)

        manifest_path = self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_sha256"][
            "contracts/v2_9/TRANSITION_RESULT.schema.json"
        ] = schema_sha
        manifest["adapter_binding_sha256"] = adapter_sha
        manifest["transition_contracts_sha256"] = hashlib.sha256(
            transitions_path.read_bytes()
        ).hexdigest()
        manifest["manifest_sha256"] = json_hash(
            {
                key: value
                for key, value in manifest.items()
                if key != "manifest_sha256"
            }
        )
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()

        self.assertIn(
            "V2_9_DETERMINISTIC_FAILURE_CONTRACT_INVALID",
            self.finding_codes(),
        )
        result = self.run_self_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "V2_9_DETERMINISTIC_FAILURE_CONTRACT_INVALID", result.stdout
        )

    def test_hash_consistent_unbound_adapter_tamper_fails_both_oracles(
        self,
    ) -> None:
        self.compile()
        adapter_path = (
            self.candidate / "PROFILE_READ_VALIDATION_ADAPTER_BINDING.json"
        )
        adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
        adapter["implementation_sha256"] = "d" * 64
        adapter["binding_contract_sha256"] = json_hash(
            {
                key: value
                for key, value in adapter.items()
                if key != "binding_contract_sha256"
            }
        )
        write_json(adapter_path, adapter)
        adapter_sha = hashlib.sha256(adapter_path.read_bytes()).hexdigest()

        transitions_path = self.candidate / "TRANSITION_CONTRACTS.json"
        transitions = json.loads(transitions_path.read_text(encoding="utf-8"))
        profile = next(
            item
            for item in transitions["contracts"]
            if item["transition_id"] == "PROFILE_READ_VALIDATION"
        )
        profile["command_contract"]["adapter_binding_sha256"] = adapter_sha
        transitions["contracts_sha256"] = json_hash(transitions["contracts"])
        write_json(transitions_path, transitions)

        manifest_path = self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["adapter_binding_sha256"] = adapter_sha
        manifest["transition_contracts_sha256"] = hashlib.sha256(
            transitions_path.read_bytes()
        ).hexdigest()
        manifest["manifest_sha256"] = json_hash(
            {
                key: value
                for key, value in manifest.items()
                if key != "manifest_sha256"
            }
        )
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()

        self.assertIn("V2_9_ADAPTER_BINDING_INVALID", self.finding_codes())
        result = self.run_self_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V2_9_ADAPTER_BINDING_INVALID", result.stdout)

    def test_hash_consistent_native_store_fingerprint_tamper_fails_both_oracles(
        self,
    ) -> None:
        self.compile()
        activation_path = (
            self.candidate / "CONTROL_EVENT_STORE_ACTIVATION_CONTRACT.json"
        )
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        native = activation["native_schema_contract"]
        native["tables"]["control_events"][0]["name"] = "event_seq"
        native["schema_contract_sha256"] = json_hash(
            {
                key: value
                for key, value in native.items()
                if key != "schema_contract_sha256"
            }
        )
        activation["native_schema_contract_sha256"] = native[
            "schema_contract_sha256"
        ]
        activation["contract_sha256"] = json_hash(
            {
                key: value
                for key, value in activation.items()
                if key != "contract_sha256"
            }
        )
        write_json(activation_path, activation)

        manifest_path = self.candidate / "V2_9_CONTROL_KERNEL_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest[
            "control_event_store_activation_contract_sha256"
        ] = hashlib.sha256(activation_path.read_bytes()).hexdigest()
        manifest["manifest_sha256"] = json_hash(
            {
                key: value
                for key, value in manifest.items()
                if key != "manifest_sha256"
            }
        )
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()

        self.assertIn(
            "V2_9_CONTROL_EVENT_STORE_ACTIVATION_INVALID",
            self.finding_codes(),
        )
        result = self.run_self_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "V2_9_CONTROL_EVENT_STORE_ACTIVATION_INVALID", result.stdout
        )

    def test_epoch9_history_root_and_source_authority_are_portable(self) -> None:
        previous_execution_root = self.root / "historical-execution-root"
        self.ir["target"]["previous_execution_root"] = str(
            previous_execution_root
        )
        self.ir["sources"][0]["authority_level"] = (
            "HUMAN_AUTHORIZED_AUTHORING_PROPOSAL"
        )

        self.compile()

        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        frozen_ir_text = (
            self.candidate / "canonical_sources/FROZEN_REQUIREMENT_IR.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn(str(previous_execution_root), frozen_ir_text)
        self.assertIn("local-binding://previous-execution-root", frozen_ir_text)
        source_manifest = json.loads(
            (self.candidate / "canonical_sources/SOURCE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        source = source_manifest["sources"][0]
        self.assertEqual(source["authority_level"], "HUMAN_APPROVED")
        self.assertEqual(
            source["declared_authority_level"],
            "HUMAN_AUTHORIZED_AUTHORING_PROPOSAL",
        )

    def test_human_review_source_authority_is_portable_for_both_oracles(self) -> None:
        self.ir["sources"][0]["authority_level"] = (
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE"
        )

        self.compile()

        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        self.assertEqual(self.run_self_check().returncode, 0)
        source_manifest = json.loads(
            (self.candidate / "canonical_sources/SOURCE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        source = source_manifest["sources"][0]
        self.assertEqual(source["authority_level"], "HUMAN_VIA_CODEX_CHAT")
        self.assertEqual(
            source["declared_authority_level"],
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE",
        )

    def test_synchronized_rehash_cannot_remove_declared_authority_semantics(self) -> None:
        self.ir["sources"][0]["authority_level"] = (
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE"
        )
        self.compile()
        manifest_path = self.candidate / "canonical_sources/SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sources"][0].pop("declared_authority_level")
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()

        self.assertIn(
            "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            self.finding_codes(),
        )
        standalone = self.run_self_check()
        self.assertNotEqual(standalone.returncode, 0)
        self.assertIn(
            "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            standalone.stdout,
        )

    def test_synchronized_rehash_cannot_relabel_both_authority_fields(self) -> None:
        self.ir["sources"][0]["authority_level"] = (
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE"
        )
        self.compile()
        manifest_path = self.candidate / "canonical_sources/SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = manifest["sources"][0]
        source["authority_level"] = "HUMAN_PROVIDED"
        source["declared_authority_level"] = "HUMAN_PROVIDED_SUPPLEMENT"
        write_json(manifest_path, manifest)
        self.refresh_closure_and_portable_hashes()

        self.assertIn(
            "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            self.finding_codes(),
        )
        standalone = self.run_self_check()
        self.assertNotEqual(standalone.returncode, 0)
        self.assertIn(
            "SOURCE_AUTHORITY_NORMALIZATION_CONTRACT_INVALID",
            standalone.stdout,
        )

    def test_typed_generation_remediation_is_bound_into_closure_receipt(self) -> None:
        self.ir["sources"][0]["authority_level"] = (
            "HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE"
        )
        remediation = {
            "status": "REQUIRED_IN_REPLACEMENT_CANDIDATE",
            "closure_receipt_required": True,
            "closure_receipt_status": (
                "CLOSURE_REQUIRED_IN_REPLACEMENT_CANDIDATE_STATIC_RECEIPT"
            ),
            "closure_requirement_kind": "GENERATION_FAILURE_REMEDIATION",
            "finding_ids": ["V021-GENERATION-SOURCE-BINDING-INCOMPLETE"],
            "superseded_candidate": "v0_21",
            "replacement_candidate": "v0_22",
            "required_closures": [
                "Normalize declared authority without changing payload identity"
            ],
            "failure": {"source_id": self.ir["sources"][0]["source_id"]},
            "authority_normalization_contract": {
                "declared_authority_level": self.ir["sources"][0][
                    "authority_level"
                ],
                "portable_authority_level": self.ir["sources"][0][
                    "authority_level"
                ].replace("_REVIEW_EVIDENCE", ""),
                "declared_authority_level_preserved": True,
                "source_payload_hash_and_copy_policy_unchanged": True,
                "unknown_authority_behavior": "FAIL_CLOSED",
            },
        }
        self.ir["target"]["v0_21_generation_failure_remediation"] = remediation
        self.compile()

        receipt_path = (
            self.candidate / "validation/HUMAN_REVIEW_CLOSURE_RECEIPT.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        entry = next(
            closure
            for closure in receipt["closures"]
            if closure["requirement_key"]
            == "v0_21_generation_failure_remediation"
        )
        self.assertEqual(
            entry["closure_requirement_kind"],
            "GENERATION_FAILURE_REMEDIATION",
        )
        self.assertEqual(entry["requirement_sha256"], json_hash(remediation))
        self.assertIn(
            "canonical_sources/SOURCE_MANIFEST.json", entry["evidence_refs"]
        )
        self.assertEqual(validate_candidate(self.candidate)["status"], "PASS")
        self.assertEqual(self.run_self_check().returncode, 0)

        receipt["closures"] = [
            closure
            for closure in receipt["closures"]
            if closure["requirement_key"]
            != "v0_21_generation_failure_remediation"
        ]
        receipt["closure_count"] = len(receipt["closures"])
        write_json(receipt_path, receipt)
        self.refresh_closure_and_portable_hashes()
        self.assertIn("HUMAN_REVIEW_CLOSURE_RECEIPT_INVALID", self.finding_codes())
        self.assertNotEqual(self.run_self_check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
