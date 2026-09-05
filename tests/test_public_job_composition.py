"""No network/media execution: model the Producer's dynamic Job boundary."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from unittest import TestCase

from harness_foundry_factory.artifact_descriptors import (
    ArtifactDescriptorError, build_artifact_descriptor, verify_job_artifact_descriptors,
)
from harness_foundry_factory.compiler import specialize_public_job_contracts
from harness_foundry_factory.semantic_contracts import (
    EXPLICIT_PRODUCTION_MODE, DETERMINISTIC_DERIVATION_POLICY, RESUMABLE_STAGE_ORDER,
)
from harness_foundry_factory.traceability import normalize_ir_coverage


def model_ir():
    value = json.loads((Path(__file__).parent / "fixtures/harness_requirement_ir.json").read_text())
    kinds = ["SOURCE_FREEZE_RECEIPT", "FUNCTION_SCENARIO_EFFECT_MATRIX", "BEFORE_AFTER_DEMO_CONTRACT",
             "TARGET_SKILL_EXECUTION_GATE_RECEIPT", "ASSET_PLAN", "LOCAL_TTS_RECEIPT",
             "AUDIO_ALIGNMENT_RECEIPT", "OBJECT_MOTION_IR", "LOCAL_RENDER_RECEIPT",
             "MEDIA_ACCEPTANCE_RECEIPT", "RESUMABLE_STAGE_RECEIPT"]
    value["atoms"] = [{"atom_id": f"ATOM-MODEL-{i}", "owner": "MAIN_HARNESS_BUILD",
                       "text_or_lossless_paraphrase": f"Produce {kind}", "verification_mode": kind}
                      for i, kind in enumerate(kinds)]
    value["coverage_edges"] = normalize_ir_coverage(value)["coverage_edges"]
    value["target"].update({"production_semantics_mode": EXPLICIT_PRODUCTION_MODE,
        "production_contract_derivation_policy": DETERMINISTIC_DERIVATION_POLICY,
        "artifact_schema_catalog": {atom["atom_id"]: {"artifact_kind": atom["verification_mode"],
            "schema": {"type": "object", "properties": {}}} for atom in value["atoms"]}})
    return value


class PublicJobCompositionTests(TestCase):
    def setUp(self):
        # Test identity from immutable in-memory source bytes, not live resolution evidence.
        self.job = {"job_id": "JOB-" + sha256(b"model-source").hexdigest()[:16].upper(),
            "source_id": "SRC-MODEL", "repository_url": "https://github.com/example/model",
            "commit_sha": sha256(b"commit").hexdigest()[:40],
            "git_tree_oid": sha256(b"tree").hexdigest()[:40], "tree_sha256": sha256(b"tree").hexdigest(),
            "resolved_tree_ref": "harness-resource://execution/evidence/cases/model-source/tree",
            "resolution_receipt_ref": "harness-resource://execution/evidence/cases/model-source/receipt.json"}

    def test_dynamic_job_reuses_complete_graph_and_requests_one_lease(self):
        original = model_ir()
        saved = deepcopy(original)
        model = specialize_public_job_contracts(original, self.job,
            declared_provider_read_refs=["harness-resource://runtime-tools/local-tts"])
        self.assertEqual(original, saved)
        index = model["artifact_index"]
        kinds = {value["artifact_kind"] for value in index.values()}
        self.assertEqual(len(index), 24)
        self.assertTrue({"NARRATION_SCRIPT", "ASSET_BINDING_RECEIPT"} <= kinds)
        render = next(value for value in index.values() if value["artifact_kind"] == "LOCAL_RENDER_RECEIPT")
        render_inputs = {index[key]["artifact_kind"] for key in render["depends_on_artifact_ids"]}
        self.assertTrue({"NARRATION_SCRIPT", "ASSET_BINDING_RECEIPT", "LOCAL_TTS_RECEIPT", "OBJECT_MOTION_IR", "BEFORE_AFTER_DEMO_CONTRACT"} <= render_inputs)
        stages = {value["expected_stage_id"] for value in index.values() if "expected_stage_id" in value}
        self.assertEqual(stages, set(RESUMABLE_STAGE_ORDER))
        for artifact in index.values():
            self.assertIn(artifact.get("job_id"), (None, self.job["job_id"]))
            self.assertTrue(set(artifact.get("depends_on_artifact_ids", [])) <= set(index))
        lease = model["lease_request"]
        self.assertIsNone(lease["authorization_ref"])
        self.assertFalse(model["execution_started"])
        self.assertEqual(lease["allowed_write_roots"], [f"harness-resource://execution/jobs/{self.job['job_id']}"])
        self.assertIn("harness-resource://runtime-tools/local-tts", lease["allowed_read_roots"])
        self.assertIn(self.job["resolved_tree_ref"], lease["allowed_read_roots"])
        self.assertIn(self.job["resolution_receipt_ref"], lease["allowed_read_roots"])

    def test_dynamic_job_rejects_other_job_read_scope(self):
        with self.assertRaisesRegex(ValueError, "crosses Job"):
            specialize_public_job_contracts(model_ir(), self.job,
                declared_provider_read_refs=["harness-resource://execution/jobs/JOB-OTHER/assets"])

    def descriptors(self, wrong_media_job=False):
        job_id = self.job["job_id"]
        root = f"harness-resource://execution/jobs/{job_id}"
        content = {"video": b"test-video-bytes-not-real-media",
            "media_acceptance_receipt": json.dumps({"job_id": "JOB-OTHER" if wrong_media_job else job_id,
                "video_ref": root + "/video", "video_sha256": sha256(b"test-video-bytes-not-real-media").hexdigest()}).encode(),
            "job_artifact_lease": json.dumps({"job_id": job_id, "allowed_write_roots": [root]}).encode()}
        descriptors = {name: build_artifact_descriptor(descriptor_id=name, logical_name=name,
            media_type="application/octet-stream", byte_size=len(raw), sha256=sha256(raw).hexdigest(),
            source_ref=root + "/" + name, producer_job_id=job_id) for name, raw in content.items()}
        return descriptors, {root + "/" + name: raw for name, raw in content.items()}

    def test_descriptor_consumer_reads_exact_bytes_and_joins_job_and_lease(self):
        descriptors, content = self.descriptors()
        reads = []
        def resolver(ref):
            reads.append(ref)
            return content[ref]
        self.assertEqual(verify_job_artifact_descriptors(descriptors, self.job["job_id"], resolver)["status"], "PASS")
        self.assertEqual(len(reads), 3)
        for wrong in ("producer_job_id", "byte_size", "sha256"):
            mutated = deepcopy(descriptors)
            mutated["video"][wrong] = {"producer_job_id": "JOB-OTHER", "byte_size": 0, "sha256": "0" * 64}[wrong]
            with self.subTest(wrong=wrong), self.assertRaises(ArtifactDescriptorError):
                verify_job_artifact_descriptors(mutated, self.job["job_id"], content.__getitem__)

    def test_matching_descriptor_hash_does_not_hide_wrong_receipt_identity(self):
        descriptors, content = self.descriptors(wrong_media_job=True)
        with self.assertRaisesRegex(ArtifactDescriptorError, "identity mismatch"):
            verify_job_artifact_descriptors(descriptors, self.job["job_id"], content.__getitem__)
