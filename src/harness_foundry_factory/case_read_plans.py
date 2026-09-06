"""Registry input plans and an in-memory reference for sequential Job reads.

This module grants no lease and touches no filesystem. Runtime adapters own
lease authentication and byte validation. Tests use callbacks, never a Lab.
"""

from hashlib import sha256
import json
from dataclasses import dataclass
from types import MappingProxyType
from .registry_evidence import RESULT_SCHEMA_REF, RECEIPT_SCHEMA_REF


CASE_EVIDENCE_ROOT = "harness-resource://execution/evidence/cases"
FIXTURE_CONTEXT = "ISOLATED_CONTRACT_FIXTURE"


REGISTRY_READ_PROTOCOL = {
    "implementation_entrypoint": "external_lab.inputs:capture_registry_inputs_v1",
    "plan_binding": "EXACT_CASE_KIND_SCHEMA_SHA256_AND_RESULT_REF",
    "job_selection": "ONE_ACTIVE_LEASE_AT_A_TIME_IN_DECLARED_PARTITION_ORDER",
    "lease_validation": "EXISTING_COMMAND_WORKPACK_JOB_SCOPE_FENCING_AND_EXPIRY_CONTRACT",
    "captured_inputs": "READ_ONLY_IN_MEMORY_BYTES_RETAINED_AFTER_LEASE_RELEASE",
    "artifact_loader": "VERIFIED_REF_TO_BYTES_CLOSURE_OF_ARTIFACT_AND_DECLARED_EVIDENCE_FIELDS",
    "empty_job_plan": "SHARED_INPUTS_ONLY_NO_JOB_LEASE_OR_JOB_READ",
    "mutation_write_scope": "CASE_EVIDENCE_ROOT_ONLY_NEVER_JOB_ARTIFACTS",
    "read_failure": "RELEASE_CURRENT_LEASE_AND_REPORT_INCONCLUSIVE_NOT_PASS",
    "baseline_entrypoint": "external_lab.inputs:prepare_registry_baseline_v1",
    "baseline_context": FIXTURE_CONTEXT,
    "baseline_partition": "CASE_RESULT_DEPENDENT_ARTIFACTS_AND_TRANSITIVE_CONSUMERS_ARE_FIXTURES",
    "fixture_setup": "CONSTRUCT_DECLARED_FIXTURE_ARTIFACT_AND_EVIDENCE_BYTES_WITHOUT_RUNNING_CASES",
    "fixture_resolution": "CASE_LOCAL_IN_MEMORY_REF_MAP_NO_LIVE_FALLBACK_NO_CANDIDATE_OVERRIDE",
    "fixture_validation": "EVERY_BASE_AND_FIXTURE_SCHEMA_AND_ALL_PURE_ORACLES_PASS_BEFORE_MUTATION",
    "fixture_persistence": "EXACT_INVOCATION_RESULT_REF_WITH_DOT_RESULT_JSON_REPLACED_BY_SLASH_INPUTS",
    "fixture_authority": "TEST_INPUT_ONLY_NOT_RUNTIME_EVIDENCE_OR_AUTHORIZATION",
    "setup_failure": "INCONCLUSIVE_NOT_PASS_NO_MUTATION_ATTEMPT",
    "result_schema_ref": RESULT_SCHEMA_REF,
    "command_receipt_schema_ref": RECEIPT_SCHEMA_REF,
    "process_observation_entrypoint": "external_lab.evidence:observe_registry_process_v1",
    "process_observer": "LOCAL_INVOCATION_SUPERVISOR_NOT_CHILD_STDOUT_PASS",
}


def registry_schema_read_plans(artifact_index):
    """Compute each schema instance's complete declared artifact closure once."""
    groups = {}
    for artifact_id, artifact in artifact_index.items():
        digest = sha256(json.dumps(artifact["schema"], ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        groups.setdefault((artifact["artifact_kind"], digest), []).append(artifact_id)
    plans = {}
    for key, base_ids in groups.items():
        seen, pending = set(), list(base_ids)
        while pending:
            artifact_id = pending.pop()
            if artifact_id in seen:
                continue
            if artifact_id not in artifact_index:
                raise ValueError("REGISTRY_READ_DEPENDENCY_UNRESOLVED:" + artifact_id)
            seen.add(artifact_id)
            pending.extend(artifact_index[artifact_id].get("depends_on_artifact_ids", []))
        # A result-dependent base cannot be acquired from its final runtime
        # location before the very Cases it summarizes have run. Isolate that
        # data, and every artifact which consumes it, as contract-test fixtures.
        fixture_ids = {i for i in seen if any(
            ref == CASE_EVIDENCE_ROOT or ref.startswith(CASE_EVIDENCE_ROOT + "/")
            for ref in artifact_index[i].get("depends_on_evidence_refs", []))}
        while True:
            consumers = {i for i in seen if fixture_ids.intersection(
                artifact_index[i].get("depends_on_artifact_ids", []))}
            if consumers <= fixture_ids:
                break
            fixture_ids.update(consumers)
        shared, jobs = [], {}
        for artifact_id in sorted(seen):
            artifact = artifact_index[artifact_id]
            job = artifact.get("job_id")
            if job:
                prefix = f"harness-resource://execution/jobs/{job}/"
                if not artifact["artifact_ref"].startswith(prefix):
                    raise ValueError("REGISTRY_READ_JOB_OWNERSHIP_MISMATCH:" + artifact_id)
            if artifact_id in fixture_ids:
                continue
            if job:
                jobs.setdefault(job, []).append(artifact_id)
            else:
                shared.append(artifact_id)
        plans[key] = {
            "base_artifact_ids": sorted(base_ids),
            "evaluation_context": FIXTURE_CONTEXT,
            "fixture_artifacts": [
                {"artifact_id": i, "artifact_ref": artifact_index[i]["artifact_ref"],
                 "dependency_artifact_ids": sorted(artifact_index[i].get("depends_on_artifact_ids", [])),
                 "evidence_refs": sorted(artifact_index[i].get("depends_on_evidence_refs", []))}
                for i in sorted(fixture_ids)],
            "shared_artifact_refs": sorted(artifact_index[i]["artifact_ref"] for i in shared),
            "job_read_partitions": [
                {"job_id": job, "artifact_refs": sorted(artifact_index[i]["artifact_ref"] for i in ids),
                 "lease_receipt_ref": "harness-resource://execution/evidence/job_artifact_leases/"
                                      f"LAB-CERTIFICATION/LAB-RUN-REGISTRY-CASE/{job}.lease.json"}
                for job, ids in sorted(jobs.items())],
        }
    return plans


def capture_registry_inputs_v1(plan, *, read_shared, acquire, read_job, release):
    """Reference control flow. Adapters validate leases before returning bytes.

    No parallel active scopes, no Job writes, and no live reads after release.
    A failure propagates instead of becoming a successful negative test.
    Referenced evidence bytes additionally use the same active scope resolver.
    """
    captured = {}
    for ref in plan["shared_artifact_refs"]:
        captured.update(read_shared(ref))
    for partition in plan["job_read_partitions"]:
        lease = acquire(partition["job_id"], partition["lease_receipt_ref"])
        try:
            for ref in partition["artifact_refs"]:
                captured.update(read_job(ref, lease))
        finally:
            release(lease)
    return captured


@dataclass(frozen=True)
class RegistryBaseline:
    """A test-input namespace, never an execution receipt or authorization."""

    bytes_by_ref: object

    def resolve(self, ref, *, evaluation_context):
        if evaluation_context != FIXTURE_CONTEXT:
            raise ValueError("CONTRACT_FIXTURE_IS_NOT_RUNTIME_EVIDENCE")
        return self.bytes_by_ref[ref]


def prepare_registry_baseline_v1(plan, captured, *, build_fixtures, validate_artifact):
    """Prepare finite fixture inputs, then check all base/fixture predicates.

    Adapters construct fixtures from frozen schemas and manifests. This helper
    neither runs Cases nor loads missing live bytes. The validator callback must
    use pure evidence predicates in FIXTURE_CONTEXT, not invoke a Case runner.
    """
    if plan.get("evaluation_context") != FIXTURE_CONTEXT:
        raise ValueError("REGISTRY_BASELINE_CONTEXT_INVALID")
    specs = plan["fixture_artifacts"]
    fixture_refs = {row["artifact_ref"] for row in specs}
    required_refs = fixture_refs | {ref for row in specs for ref in row["evidence_refs"]}
    if fixture_refs.intersection(captured):
        raise ValueError("CASE_DERIVED_BASE_MUST_NOT_BE_READ_FROM_RUNTIME")
    inputs = dict(captured)
    if specs:
        generated = build_fixtures(specs, MappingProxyType(inputs))
        if not isinstance(generated, dict) or not required_refs <= set(generated) | set(inputs):
            raise ValueError("REGISTRY_FIXTURE_INPUTS_INCOMPLETE")
        if set(generated).intersection(inputs) or any(
            ref not in fixture_refs and not ref.startswith(CASE_EVIDENCE_ROOT + "/")
            for ref in generated
        ):
            raise ValueError("REGISTRY_FIXTURE_REFERENCE_OVERRIDE")
        inputs.update(generated)
    if any(not isinstance(value, bytes) for value in inputs.values()):
        raise ValueError("REGISTRY_BASELINE_REQUIRES_BYTES")
    baseline = RegistryBaseline(MappingProxyType(inputs))
    for artifact_id in sorted(set(plan["base_artifact_ids"]) | {row["artifact_id"] for row in specs}):
        if validate_artifact(artifact_id, baseline) is not True:
            raise ValueError("REGISTRY_BASELINE_SETUP_FAILED:" + artifact_id)
    return baseline
