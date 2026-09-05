"""Content descriptors and digest-projection diagnostics.

A descriptor binds a digest to immutable bytes.  Validation proves only that
the record is well formed and internally consistent; it does not authenticate
the producer, source, or bytes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_DESCRIPTOR_FIELDS = {
    "descriptor_id",
    "logical_name",
    "media_type",
    "byte_size",
    "sha256",
    "source_ref",
}
OPTIONAL_DESCRIPTOR_FIELDS = {"producer_job_id"}
REGISTRY_FIELDS = {"schema_version", "descriptors"}

HASH_WITHOUT_INDEPENDENT_CONSUMER = "HASH_WITHOUT_INDEPENDENT_CONSUMER"
DUPLICATE_DIGEST_PROJECTION = "DUPLICATE_DIGEST_PROJECTION"
HASH_OF_HASH_WITHOUT_NEW_BOUNDARY = "HASH_OF_HASH_WITHOUT_NEW_BOUNDARY"


ARTIFACT_DESCRIPTOR_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:harness-foundry:artifact-descriptor:v1",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(REQUIRED_DESCRIPTOR_FIELDS),
    "properties": {
        "descriptor_id": {"type": "string", "minLength": 1},
        "logical_name": {"type": "string", "minLength": 1},
        "media_type": {"type": "string", "minLength": 1},
        "byte_size": {"type": "integer", "minimum": 0},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "source_ref": {"type": "string", "minLength": 1},
        "producer_job_id": {"type": "string", "minLength": 1},
    },
}

# Embed the shape without re-declaring the same schema resource ID multiple
# times inside a parent schema.
EMBEDDED_ARTIFACT_DESCRIPTOR_SCHEMA: dict[str, Any] = {
    key: value
    for key, value in ARTIFACT_DESCRIPTOR_SCHEMA.items()
    if key not in {"$schema", "$id"}
}

# Job ownership is required by this consumer, not by all content descriptors.
JOB_ARTIFACT_DESCRIPTOR_SCHEMA = {
    **EMBEDDED_ARTIFACT_DESCRIPTOR_SCHEMA,
    "required": sorted(REQUIRED_DESCRIPTOR_FIELDS | {"producer_job_id"}),
}

ARTIFACT_DESCRIPTOR_REGISTRY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:harness-foundry:artifact-descriptor-registry:v1",
    "type": "object",
    "additionalProperties": False,
    "required": sorted(REGISTRY_FIELDS),
    "properties": {
        "schema_version": {"const": "1.0"},
        "descriptors": {
            "type": "array",
            "items": ARTIFACT_DESCRIPTOR_SCHEMA,
        },
    },
}


class ArtifactDescriptorError(ValueError):
    """Raised when a descriptor or registry violates the v1 contract."""


def _require_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactDescriptorError(f"{name} must be a non-empty string")
    return value


def validate_artifact_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized descriptor after strict structural validation."""

    if not isinstance(value, Mapping):
        raise ArtifactDescriptorError("artifact descriptor must be a mapping")
    fields = set(value)
    if not REQUIRED_DESCRIPTOR_FIELDS <= fields:
        missing = sorted(REQUIRED_DESCRIPTOR_FIELDS - fields)
        raise ArtifactDescriptorError(f"artifact descriptor fields missing: {missing}")
    unexpected = fields - REQUIRED_DESCRIPTOR_FIELDS - OPTIONAL_DESCRIPTOR_FIELDS
    if unexpected:
        raise ArtifactDescriptorError(
            f"artifact descriptor fields are not exact: {sorted(unexpected)}"
        )

    descriptor = dict(value)
    for field in ("descriptor_id", "logical_name", "media_type", "source_ref"):
        _require_non_empty_string(field, descriptor[field])
    if "producer_job_id" in descriptor:
        _require_non_empty_string("producer_job_id", descriptor["producer_job_id"])

    byte_size = descriptor["byte_size"]
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
        raise ArtifactDescriptorError("byte_size must be a non-negative integer")
    digest = descriptor["sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ArtifactDescriptorError("sha256 must be a lowercase SHA-256")
    return descriptor


def build_artifact_descriptor(
    *,
    descriptor_id: str,
    logical_name: str,
    media_type: str,
    byte_size: int,
    sha256: str,
    source_ref: str,
    producer_job_id: str | None = None,
) -> dict[str, Any]:
    """Build and validate the minimal descriptor used at byte boundaries."""

    descriptor: dict[str, Any] = {
        "descriptor_id": descriptor_id,
        "logical_name": logical_name,
        "media_type": media_type,
        "byte_size": byte_size,
        "sha256": sha256,
        "source_ref": source_ref,
    }
    if producer_job_id is not None:
        descriptor["producer_job_id"] = producer_job_id
    return validate_artifact_descriptor(descriptor)


def verify_job_artifact_descriptors(artifacts, job_id, resolver):
    """Reference consumer: join Job identity, descriptor bytes and media/lease."""
    import json
    from hashlib import sha256

    verified = {}
    for name in ("video", "media_acceptance_receipt", "job_artifact_lease"):
        descriptor = validate_artifact_descriptor(artifacts[name])
        if descriptor.get("producer_job_id") != job_id:
            raise ArtifactDescriptorError("descriptor belongs to another Job")
        content = resolver(descriptor["source_ref"])
        if (not isinstance(content, bytes) or len(content) != descriptor["byte_size"]
                or sha256(content).hexdigest() != descriptor["sha256"]):
            raise ArtifactDescriptorError("descriptor bytes do not match")
        verified[name] = content
    media = json.loads(verified["media_acceptance_receipt"])
    lease = json.loads(verified["job_artifact_lease"])
    if media.get("job_id") != job_id or lease.get("job_id") != job_id:
        raise ArtifactDescriptorError("media/lease Job identity mismatch")
    video = artifacts["video"]
    if media.get("video_ref") != video["source_ref"] or media.get("video_sha256") != video["sha256"]:
        raise ArtifactDescriptorError("media receipt describes another video")
    roots = lease.get("allowed_write_roots", [])
    if not all(any(descriptor["source_ref"] == root or descriptor["source_ref"].startswith(root.rstrip("/") + "/")
                   for root in roots) for name, descriptor in artifacts.items() if name != "job_artifact_lease"):
        raise ArtifactDescriptorError("artifacts are outside the Job lease")
    return {"status": "PASS", "job_id": job_id, "verified_artifacts": sorted(verified)}


def diagnose_candidate_hash_projections(root):
    """Bounded, non-blocking inventory; counts projections, not security failures.

    This does not read runtime artifacts or infer consumer identity from a hash.
    It measures this diagnostic's IO, not total Factory digest computation cost.
    """
    import json
    from pathlib import Path
    from time import perf_counter

    started = perf_counter()
    relative = "validation/CASE_EXECUTION_MANIFEST.json"
    path = Path(root) / relative
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, ValueError):
        return {"status": "NOT_AVAILABLE", "blocking": False}
    projections = []

    def visit(value, pointer):
        if isinstance(value, dict):
            for key, digest in value.items():
                if key.endswith("_sha256") and isinstance(digest, str) and SHA256_RE.fullmatch(digest):
                    ref = value.get(key[:-7] + "_ref")
                    if isinstance(ref, str):
                        projections.append({
                            "projection_ref": relative + "#" + pointer + "/" + key,
                            "descriptor_id": ref, "producer_id": "CANDIDATE_PRODUCER",
                            "sha256": digest, "subject_kind": "IMMUTABLE_BYTES",
                            "introduces_new_boundary": False,
                        })
                visit(digest, pointer + "/" + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, pointer + "/" + str(index))

    visit(document, "")
    findings = audit_hash_projections(projections)
    counts = defaultdict(int)
    for finding in findings:
        counts[finding["code"]] += 1
    return {
        "status": "DIAGNOSTIC_ONLY", "blocking": False,
        "scope": relative, "projection_count": len(projections),
        "unique_referenced_objects": len({item["descriptor_id"] for item in projections}),
        "finding_counts": dict(counts), "sample_findings": findings[:10],
        "consumer_identity": "NOT_INFERRED_FROM_DOCUMENT",
        "redundant_digest_computations": "NOT_MEASURED",
        "diagnostic_cost": {"documents_read": 1, "bytes_read": len(raw),
                            "digest_computations": 0, "elapsed_seconds": perf_counter() - started},
    }


def _logical_fingerprint(descriptor: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        descriptor["media_type"],
        descriptor["byte_size"],
        descriptor["sha256"],
        descriptor["source_ref"],
        descriptor.get("producer_job_id"),
    )


def validate_artifact_descriptor_registry(
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate descriptor uniqueness and logical-object consistency."""

    if not isinstance(registry, Mapping) or set(registry) != REGISTRY_FIELDS:
        raise ArtifactDescriptorError("artifact descriptor registry fields are not exact")
    if registry.get("schema_version") != "1.0":
        raise ArtifactDescriptorError("artifact descriptor registry version must be 1.0")
    raw_descriptors = registry.get("descriptors")
    if (
        not isinstance(raw_descriptors, Sequence)
        or isinstance(raw_descriptors, (str, bytes, bytearray))
    ):
        raise ArtifactDescriptorError("descriptors must be an array")

    descriptors: list[dict[str, Any]] = []
    descriptor_ids: set[str] = set()
    fingerprints_by_name: dict[str, tuple[Any, ...]] = {}
    fingerprints_by_source: dict[str, tuple[Any, ...]] = {}
    for raw_descriptor in raw_descriptors:
        descriptor = validate_artifact_descriptor(raw_descriptor)
        descriptor_id = descriptor["descriptor_id"]
        if descriptor_id in descriptor_ids:
            raise ArtifactDescriptorError(
                f"duplicate descriptor_id: {descriptor_id}"
            )
        descriptor_ids.add(descriptor_id)

        fingerprint = _logical_fingerprint(descriptor)
        logical_name = descriptor["logical_name"]
        source_ref = descriptor["source_ref"]
        if (
            logical_name in fingerprints_by_name
            and fingerprints_by_name[logical_name] != fingerprint
        ):
            raise ArtifactDescriptorError(
                f"conflicting descriptor for logical_name: {logical_name}"
            )
        if (
            source_ref in fingerprints_by_source
            and fingerprints_by_source[source_ref] != fingerprint
        ):
            raise ArtifactDescriptorError(
                f"conflicting descriptor for source_ref: {source_ref}"
            )
        fingerprints_by_name[logical_name] = fingerprint
        fingerprints_by_source[source_ref] = fingerprint
        descriptors.append(descriptor)

    return {"schema_version": "1.0", "descriptors": descriptors}


def _audit_projection(projection: Mapping[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(projection, Mapping):
        raise ArtifactDescriptorError(f"hash projection {index} must be a mapping")
    projected = dict(projection)
    projection_ref = _require_non_empty_string(
        f"hash projection {index}.projection_ref", projected.get("projection_ref")
    )
    for field in ("descriptor_id", "producer_id"):
        _require_non_empty_string(
            f"hash projection {projection_ref}.{field}", projected.get(field)
        )
    digest = projected.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ArtifactDescriptorError(
            f"hash projection {projection_ref}.sha256 must be a lowercase SHA-256"
        )
    subject_kind = projected.get("subject_kind")
    if subject_kind not in {"IMMUTABLE_BYTES", "DIGEST"}:
        raise ArtifactDescriptorError(
            f"hash projection {projection_ref}.subject_kind is invalid"
        )
    introduces_new_boundary = projected.get("introduces_new_boundary")
    if not isinstance(introduces_new_boundary, bool):
        raise ArtifactDescriptorError(
            f"hash projection {projection_ref}.introduces_new_boundary must be boolean"
        )
    return projected


def audit_hash_projections(
    projections: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Report redundant or unconsumed digest projections.

    Each projection describes a location that embeds a digest.  A meaningful
    projection names a verifier independent of the producer, the boundary at
    which it verifies, and the action taken on mismatch.  A hash of another
    digest is justified only when it introduces a new boundary.
    """

    if not isinstance(projections, Sequence) or isinstance(
        projections, (str, bytes, bytearray)
    ):
        raise ArtifactDescriptorError("hash projections must be an array")

    normalized = [
        _audit_projection(projection, index)
        for index, projection in enumerate(projections)
    ]
    findings: list[dict[str, Any]] = []
    duplicate_groups: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for projection in normalized:
        projection_ref = projection["projection_ref"]
        producer_id = projection["producer_id"]
        consumer_id = projection.get("consumer_id")
        boundary_id = projection.get("boundary_id")
        mismatch_action = projection.get("mismatch_action")
        if (
            not isinstance(consumer_id, str)
            or not consumer_id
            or consumer_id == producer_id
            or not isinstance(boundary_id, str)
            or not boundary_id
            or not isinstance(mismatch_action, str)
            or not mismatch_action
        ):
            findings.append(
                {
                    "code": HASH_WITHOUT_INDEPENDENT_CONSUMER,
                    "projection_ref": projection_ref,
                    "descriptor_id": projection["descriptor_id"],
                }
            )
        if (
            projection["subject_kind"] == "DIGEST"
            and projection["introduces_new_boundary"] is not True
        ):
            findings.append(
                {
                    "code": HASH_OF_HASH_WITHOUT_NEW_BOUNDARY,
                    "projection_ref": projection_ref,
                    "descriptor_id": projection["descriptor_id"],
                }
            )

        duplicate_groups[
            (
                projection["descriptor_id"],
                projection["sha256"],
                consumer_id if isinstance(consumer_id, str) else "",
                boundary_id if isinstance(boundary_id, str) else "",
            )
        ].append(projection_ref)

    for (descriptor_id, _digest, _consumer_id, _boundary_id), refs in sorted(
        duplicate_groups.items()
    ):
        unique_refs = sorted(set(refs))
        if len(unique_refs) > 1:
            findings.append(
                {
                    "code": DUPLICATE_DIGEST_PROJECTION,
                    "descriptor_id": descriptor_id,
                    "projection_refs": unique_refs,
                }
            )

    return sorted(
        findings,
        key=lambda finding: (
            finding["code"],
            finding.get("projection_ref", ""),
            tuple(finding.get("projection_refs", ())),
        ),
    )
