from copy import deepcopy
import unittest

from harness_foundry_factory.case_read_plans import (
    FIXTURE_CONTEXT, registry_schema_read_plans, capture_registry_inputs_v1,
    prepare_registry_baseline_v1,
)
from harness_foundry_factory.compiler import _external_lab_case_command_contracts, _bind_commands_to_workpack_artifact_roots
from harness_foundry_factory.validator import _independent_registry_read_plans, _job_artifact_lease_contract_is_valid


def graph():
    index = {}
    for job in ("alpha", "beta", "gamma"):
        index[job] = {"artifact_kind": "INPUT", "job_id": job,
            "artifact_ref": f"harness-resource://execution/jobs/{job}/artifacts/input.json",
            "schema": {"type": "object", "properties": {"job_id": {"const": job}}},
            "depends_on_artifact_ids": []}
    index["shared"] = {"artifact_kind": "AGGREGATE", "job_id": None,
        "artifact_ref": "harness-resource://execution/artifacts/aggregate.json",
        "schema": {"type": "object"}, "depends_on_artifact_ids": ["alpha", "beta", "gamma"]}
    index["alpha"]["depends_on_artifact_ids"] = ["alpha-dependency"]
    index["alpha-dependency"] = {"artifact_kind": "NARRATION", "job_id": "alpha",
        "artifact_ref": "harness-resource://execution/jobs/alpha/artifacts/narration.json",
        "schema": {"type": "object", "properties": {"sentences": {"type": "array"}}},
        "depends_on_artifact_ids": []}
    return index


class RegistryReadPlanTests(unittest.TestCase):
    def test_case_derived_base_is_a_fixture_not_a_live_result_dependency(self):
        index = graph()
        result_ref = "harness-resource://execution/evidence/cases/registry/check/result.json"
        index["shared"]["depends_on_evidence_refs"] = [result_ref]
        plans = registry_schema_read_plans(index)
        plan = next(p for (kind, _), p in plans.items() if kind == "AGGREGATE")
        self.assertNotIn(index["shared"]["artifact_ref"], plan["shared_artifact_refs"])
        self.assertEqual(plan["fixture_artifacts"], [{
            "artifact_id": "shared", "artifact_ref": index["shared"]["artifact_ref"],
            "dependency_artifact_ids": ["alpha", "beta", "gamma"],
            "evidence_refs": [result_ref],
        }])
        self.assertEqual(plan["evaluation_context"], "ISOLATED_CONTRACT_FIXTURE")
        self.assertEqual([p["job_id"] for p in plan["job_read_partitions"]], ["alpha", "beta", "gamma"])
        self.assertEqual(plans, _independent_registry_read_plans(index))

    def test_case_result_dependency_propagates_without_an_artifact_kind_exception(self):
        index = graph()
        index["alpha-dependency"]["depends_on_evidence_refs"] = [
            "harness-resource://execution/evidence/cases/contract-check.result.json"]
        plans = registry_schema_read_plans(index)
        plan = next(p for (kind, _), p in plans.items() if kind == "AGGREGATE")
        self.assertEqual([x["artifact_id"] for x in plan["fixture_artifacts"]],
                         ["alpha", "alpha-dependency", "shared"])
        self.assertEqual([p["job_id"] for p in plan["job_read_partitions"]], ["beta", "gamma"])
        self.assertEqual(plan["shared_artifact_refs"], [])
        self.assertEqual(plans, _independent_registry_read_plans(index))

    def test_fixture_setup_is_finite_validated_and_not_live_certification(self):
        index = graph()
        result_ref = "harness-resource://execution/evidence/cases/contract-check.result.json"
        index["shared"]["depends_on_evidence_refs"] = [result_ref]
        plan = next(p for (kind, _), p in registry_schema_read_plans(index).items() if kind == "AGGREGATE")
        artifact_ref = index["shared"]["artifact_ref"]
        live = {index[j]["artifact_ref"]: b'{"input":true}' for j in ("alpha", "beta", "gamma", "alpha-dependency")}
        calls = []
        def build(specs, captured):
            calls.append("setup")
            self.assertNotIn(artifact_ref, captured)
            self.assertNotIn(result_ref, captured)
            with self.assertRaises(TypeError):
                captured[artifact_ref] = b"overwritten"
            return {artifact_ref: b'{"results":[true]}', result_ref: b'{"status":"PASS"}'}
        def validate(identity, context):
            calls.append(("validate", identity))
            self.assertEqual(context.resolve(artifact_ref, evaluation_context=FIXTURE_CONTEXT), b'{"results":[true]}')
            return True
        baseline = prepare_registry_baseline_v1(plan, live, build_fixtures=build, validate_artifact=validate)
        self.assertEqual(calls, ["setup", ("validate", "shared")])
        self.assertNotIn(artifact_ref, live)
        with self.assertRaisesRegex(ValueError, "NOT_RUNTIME_EVIDENCE"):
            baseline.resolve(result_ref, evaluation_context="RUNTIME_EVIDENCE")
        with self.assertRaises(KeyError):
            baseline.resolve("missing-live-ref", evaluation_context=FIXTURE_CONTEXT)
        with self.assertRaisesRegex(ValueError, "SETUP_FAILED"):
            prepare_registry_baseline_v1(plan, live, build_fixtures=build, validate_artifact=lambda *_: False)
        with self.assertRaisesRegex(ValueError, "INPUTS_INCOMPLETE"):
            prepare_registry_baseline_v1(plan, live, build_fixtures=lambda *_: {artifact_ref: b"{}"}, validate_artifact=validate)
        with self.assertRaisesRegex(ValueError, "REFERENCE_OVERRIDE"):
            prepare_registry_baseline_v1(plan, live, build_fixtures=lambda *_: {
                artifact_ref: b"{}", result_ref: b"{}", "harness-resource://candidate/registry.json": b"{}"},
                validate_artifact=validate)
        with self.assertRaisesRegex(ValueError, "MUST_NOT_BE_READ_FROM_RUNTIME"):
            prepare_registry_baseline_v1(plan, {**live, artifact_ref: b"{}"}, build_fixtures=build, validate_artifact=validate)

    def test_live_only_baseline_does_not_build_fixtures_or_skip_base_validation(self):
        index = graph()
        plan = next(p for (kind, _), p in registry_schema_read_plans(index).items()
                    if kind == "INPUT" and p["base_artifact_ids"] == ["beta"])
        calls = []
        def no_build(*_):
            self.fail("No synthetic artifacts are required for this base")
        baseline = prepare_registry_baseline_v1(plan, {index["beta"]["artifact_ref"]: b"{}"},
            build_fixtures=no_build, validate_artifact=lambda identity, _: calls.append(identity) is None)
        self.assertEqual(calls, ["beta"])
        self.assertEqual(baseline.resolve(index["beta"]["artifact_ref"], evaluation_context=FIXTURE_CONTEXT), b"{}")

    def test_registry_runner_has_read_only_lease_capability(self):
        commands = _external_lab_case_command_contracts(executable="python", repository_root="repo",
            candidate_root="harness-resource://candidate", execution_root="harness-resource://execution")
        bound = _bind_commands_to_workpack_artifact_roots({c["command_id"]: c for c in commands},
            ["LAB-RUN-REGISTRY-CASE"], [], ["harness-resource://execution/jobs/alpha/artifacts"],
            workpack_id="LAB-CERTIFICATION")[0]
        self.assertTrue(bound["job_artifact_lease_required"])
        self.assertEqual(bound["job_artifact_write_scopes"], [])
        self.assertEqual(bound["job_artifact_lease_contract"]["selection_cardinality"],
                         "EXACTLY_ONE_ACTIVE_JOB_LEASE_PER_REGISTRY_READ_PARTITION")
        self.assertIn("--read-plan-ref", bound["parameter_contract"]["required_flags"])
        self.assertTrue(_job_artifact_lease_contract_is_valid(bound, workpack_id="LAB-CERTIFICATION"))
        bound["job_artifact_lease_required"] = False
        self.assertFalse(_job_artifact_lease_contract_is_valid(bound, workpack_id="LAB-CERTIFICATION"))

    def test_read_plan_covers_single_job_and_shared_aggregate_transitively(self):
        plans = registry_schema_read_plans(graph())
        single = next(p for (kind, _), p in plans.items() if kind == "INPUT" and p["base_artifact_ids"] == ["alpha"])
        self.assertEqual([p["job_id"] for p in single["job_read_partitions"]], ["alpha"])
        self.assertEqual(len(single["job_read_partitions"][0]["artifact_refs"]), 2)
        aggregate = next(p for (kind, _), p in plans.items() if kind == "AGGREGATE")
        self.assertEqual([p["job_id"] for p in aggregate["job_read_partitions"]], ["alpha", "beta", "gamma"])
        self.assertEqual(len(aggregate["shared_artifact_refs"]), 1)
        self.assertEqual(plans, _independent_registry_read_plans(graph()))
        damaged = deepcopy(plans)
        for key in damaged:
            damaged[key]["job_read_partitions"] = []
        self.assertNotEqual(damaged, _independent_registry_read_plans(graph()))

    def test_reference_reader_releases_each_lease_before_next_job(self):
        plan = next(p for (kind, _), p in registry_schema_read_plans(graph()).items() if kind == "AGGREGATE")
        active, calls = [], []
        def acquire(job, ref):
            self.assertEqual(active, [])
            self.assertIn('/'+job+'.lease.json', ref)
            active.append(job)
            calls.append(("acquire", job))
            return job
        def read(ref, lease):
            self.assertEqual(active, [lease])
            self.assertIn('/jobs/'+lease+'/', ref)
            return {ref: ref.encode()}
        def release(lease):
            self.assertEqual(active.pop(), lease)
            calls.append(("release", lease))
        data = capture_registry_inputs_v1(plan, read_shared=lambda ref: {ref: ref.encode()}, acquire=acquire, read_job=read, release=release)
        self.assertEqual(len(data), 5)
        self.assertEqual(calls, [(op, job) for job in ("alpha", "beta", "gamma") for op in ("acquire", "release")])
        calls.clear()
        def fail(ref, lease):
            raise ValueError("input unavailable")
        with self.assertRaisesRegex(ValueError, "input unavailable"):
            capture_registry_inputs_v1(plan, read_shared=lambda ref: {ref: b"input"}, acquire=acquire, read_job=fail, release=release)
        self.assertEqual(calls, [("acquire", "alpha"), ("release", "alpha")])
        self.assertEqual(active, [])

    def test_shared_only_plan_does_not_acquire_unrelated_job_lease(self):
        index = graph()
        index["shared"]["depends_on_artifact_ids"] = []
        plan = next(p for (kind, _), p in registry_schema_read_plans(index).items() if kind == "AGGREGATE")
        def forbidden(*args):
            self.fail("shared-only Case must not touch Job scopes")
        self.assertEqual(len(capture_registry_inputs_v1(plan, read_shared=lambda ref: {ref: b"input"},
            acquire=forbidden, read_job=forbidden, release=forbidden)), 1)

    def test_missing_dependency_or_wrong_job_owner_is_not_a_plan(self):
        index = graph()
        del index["alpha-dependency"]
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_UNRESOLVED"):
            registry_schema_read_plans(index)
        index = graph()
        index["alpha"]["artifact_ref"] = index["beta"]["artifact_ref"]
        with self.assertRaisesRegex(ValueError, "JOB_OWNERSHIP_MISMATCH"):
            registry_schema_read_plans(index)
