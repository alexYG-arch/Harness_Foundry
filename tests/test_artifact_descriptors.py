"""Tests for minimal byte descriptors and digest projection diagnostics."""

from __future__ import annotations

import unittest

from harness_foundry_factory.artifact_descriptors import (
    ARTIFACT_DESCRIPTOR_REGISTRY_SCHEMA,
    ARTIFACT_DESCRIPTOR_SCHEMA,
    DUPLICATE_DIGEST_PROJECTION,
    HASH_OF_HASH_WITHOUT_NEW_BOUNDARY,
    HASH_WITHOUT_INDEPENDENT_CONSUMER,
    ArtifactDescriptorError,
    audit_hash_projections,
    build_artifact_descriptor,
    validate_artifact_descriptor,
    validate_artifact_descriptor_registry,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _descriptor(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "descriptor_id": "DESC-VIDEO-001",
        "logical_name": "final_video",
        "media_type": "video/mp4",
        "byte_size": 1234,
        "sha256": DIGEST_A,
        "source_ref": "job://render/final.mp4",
        "producer_job_id": "JOB-RENDER",
    }
    value.update(overrides)
    return value


def _projection(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "projection_ref": "receipt://render/output",
        "descriptor_id": "DESC-VIDEO-001",
        "sha256": DIGEST_A,
        "subject_kind": "IMMUTABLE_BYTES",
        "producer_id": "JOB-RENDER",
        "consumer_id": "VALIDATOR",
        "boundary_id": "JOB-TO-CANDIDATE",
        "mismatch_action": "REJECT_RECEIPT",
        "introduces_new_boundary": True,
    }
    value.update(overrides)
    return value


class ArtifactDescriptorTests(unittest.TestCase):
    def test_schema_is_strict_and_exposes_required_fields(self) -> None:
        self.assertFalse(ARTIFACT_DESCRIPTOR_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(ARTIFACT_DESCRIPTOR_SCHEMA["required"]),
            {
                "descriptor_id",
                "logical_name",
                "media_type",
                "byte_size",
                "sha256",
                "source_ref",
            },
        )
        self.assertFalse(
            ARTIFACT_DESCRIPTOR_REGISTRY_SCHEMA["additionalProperties"]
        )

    def test_builder_returns_minimal_valid_descriptor(self) -> None:
        descriptor = build_artifact_descriptor(
            descriptor_id="DESC-AUDIO-001",
            logical_name="narration_audio",
            media_type="audio/wav",
            byte_size=0,
            sha256=DIGEST_A,
            source_ref="job://tts/narration.wav",
        )

        self.assertEqual(descriptor["byte_size"], 0)
        self.assertNotIn("producer_job_id", descriptor)

    def test_descriptor_rejects_uppercase_digest_negative_size_and_extra_field(self) -> None:
        invalid_values = (
            _descriptor(sha256="A" * 64),
            _descriptor(byte_size=-1),
            _descriptor(byte_size=True),
            _descriptor(unexpected=True),
        )

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ArtifactDescriptorError):
                    validate_artifact_descriptor(value)

    def test_descriptor_validation_does_not_claim_authenticity(self) -> None:
        descriptor = validate_artifact_descriptor(_descriptor())

        self.assertNotIn("authentic", descriptor)
        self.assertNotIn("verified", descriptor)


class ArtifactDescriptorRegistryTests(unittest.TestCase):
    def test_registry_accepts_distinct_logical_objects(self) -> None:
        registry = validate_artifact_descriptor_registry(
            {
                "schema_version": "1.0",
                "descriptors": [
                    _descriptor(),
                    _descriptor(
                        descriptor_id="DESC-AUDIO-001",
                        logical_name="narration_audio",
                        media_type="audio/wav",
                        byte_size=4321,
                        sha256=DIGEST_B,
                        source_ref="job://tts/narration.wav",
                        producer_job_id="JOB-TTS",
                    ),
                ],
            }
        )

        self.assertEqual(len(registry["descriptors"]), 2)

    def test_registry_rejects_duplicate_descriptor_id(self) -> None:
        with self.assertRaisesRegex(ArtifactDescriptorError, "duplicate descriptor_id"):
            validate_artifact_descriptor_registry(
                {
                    "schema_version": "1.0",
                    "descriptors": [_descriptor(), _descriptor()],
                }
            )

    def test_registry_rejects_conflicting_logical_name_or_source(self) -> None:
        conflicts = (
            _descriptor(
                descriptor_id="DESC-VIDEO-002",
                sha256=DIGEST_B,
                source_ref="job://render/replaced.mp4",
            ),
            _descriptor(
                descriptor_id="DESC-VIDEO-002",
                logical_name="alternate_video",
                sha256=DIGEST_B,
            ),
        )

        for conflict in conflicts:
            with self.subTest(conflict=conflict):
                with self.assertRaises(ArtifactDescriptorError):
                    validate_artifact_descriptor_registry(
                        {
                            "schema_version": "1.0",
                            "descriptors": [_descriptor(), conflict],
                        }
                    )


class HashProjectionAuditTests(unittest.TestCase):
    def test_meaningful_byte_projection_has_no_findings(self) -> None:
        self.assertEqual(audit_hash_projections([_projection()]), [])

    def test_reports_missing_independent_consumer_without_count_threshold(self) -> None:
        findings = audit_hash_projections(
            [_projection(consumer_id="JOB-RENDER", mismatch_action="")]
        )

        self.assertEqual(
            [finding["code"] for finding in findings],
            [HASH_WITHOUT_INDEPENDENT_CONSUMER],
        )

    def test_reports_duplicate_projection_for_same_consumer_boundary(self) -> None:
        findings = audit_hash_projections(
            [
                _projection(),
                _projection(projection_ref="manifest://candidate/final_video"),
            ]
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["code"], DUPLICATE_DIGEST_PROJECTION)
        self.assertEqual(
            findings[0]["projection_refs"],
            ["manifest://candidate/final_video", "receipt://render/output"],
        )

    def test_same_digest_at_distinct_boundaries_is_not_duplicate(self) -> None:
        findings = audit_hash_projections(
            [
                _projection(),
                _projection(
                    projection_ref="release://publication/final_video",
                    consumer_id="RELEASE-VALIDATOR",
                    boundary_id="CANDIDATE-TO-RELEASE",
                ),
            ]
        )

        self.assertEqual(findings, [])

    def test_reports_hash_of_hash_without_new_boundary(self) -> None:
        findings = audit_hash_projections(
            [
                _projection(
                    subject_kind="DIGEST",
                    introduces_new_boundary=False,
                )
            ]
        )

        self.assertEqual(
            [finding["code"] for finding in findings],
            [HASH_OF_HASH_WITHOUT_NEW_BOUNDARY],
        )


if __name__ == "__main__":
    unittest.main()
