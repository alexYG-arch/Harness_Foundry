"""Minimum Requirement Completion and Control Domain tests for v2.9."""

from __future__ import annotations

import unittest

from harness_foundry_factory.requirement_completion import (
    dependency_invalidation_events,
    evaluate_control_domain,
    evaluate_requirement_completion,
)


def contract() -> dict:
    return {
        "schema_version": "2.9",
        "requirement_id": "REQ-29-CONTROL",
        "instance_id": "INSTANCE-E9",
        "applicability_decision": "APPLICABLE",
        "mandatory_subrequirements": ["SUB-A", "SUB-B"],
        "required_workpacks": ["WP-CONTROL"],
        "required_cases": ["CASE-POSITIVE"],
        "required_evidence": ["EVIDENCE-CONTROL"],
        "required_oracles": ["ORACLE-CONTROL"],
        "invalidation_dependencies": ["POLICY-SHA", "PROFILE-SHA"],
    }


def observations() -> dict:
    binding = {"requirement_id": "REQ-29-CONTROL", "instance_id": "INSTANCE-E9"}
    return {
        "subrequirements": {
            "SUB-A": {"status": "SATISFIED"},
            "SUB-B": {"status": "SATISFIED"},
        },
        "workpacks": {"WP-CONTROL": {"status": "PASS_VALID"}},
        "cases": {"CASE-POSITIVE": {"status": "PASS", **binding}},
        "evidence": {"EVIDENCE-CONTROL": {"status": "PASS", **binding}},
        "oracles": {"ORACLE-CONTROL": {"status": "PASS", **binding}},
        "findings": [],
        "invalidated_dependencies": [],
        "verification_level": "FIXTURE",
    }


class RequirementCompletionTests(unittest.TestCase):
    def test_workpack_pass_alone_cannot_close_parent_requirement(self) -> None:
        partial = {"workpacks": {"WP-CONTROL": {"status": "PASS_VALID"}}}
        record = evaluate_requirement_completion(contract(), partial)
        self.assertEqual(record["state"], "PARTIAL")
        self.assertTrue(record["blockers"])

    def test_all_explicit_obligations_close_requirement(self) -> None:
        record = evaluate_requirement_completion(contract(), observations())
        self.assertEqual(record["state"], "SATISFIED")
        self.assertEqual(record["verification_level"], "FIXTURE")
        self.assertEqual(record["blockers"], [])

    def test_wrong_instance_stale_evidence_and_bad_applicability_fail_closed(self) -> None:
        wrong = observations()
        wrong["evidence"]["EVIDENCE-CONTROL"]["instance_id"] = "OTHER"
        record = evaluate_requirement_completion(contract(), wrong)
        self.assertEqual(record["state"], "PARTIAL")
        self.assertIn(
            "WRONG_OR_STALE_EVIDENCE_INSTANCE",
            {item["code"] for item in record["blockers"]},
        )
        not_applicable = contract()
        not_applicable["applicability_decision"] = "NOT_APPLICABLE"
        with self.assertRaisesRegex(ValueError, "N/A requires a decision receipt"):
            evaluate_requirement_completion(not_applicable, {})

    def test_declared_dependency_invalidation_reopens_requirement(self) -> None:
        emitted = dependency_invalidation_events(
            contract(), ["UNDECLARED", "POLICY-SHA"]
        )
        self.assertEqual(len(emitted), 1)
        invalid = observations()
        invalid["invalidated_dependencies"] = ["POLICY-SHA"]
        record = evaluate_requirement_completion(contract(), invalid)
        self.assertEqual(record["state"], "INVALIDATED")

    def test_shared_validator_is_not_independent(self) -> None:
        domain = {
            "claim_id": "CLAIM-CONTROL",
            "assurance_level": "INDEPENDENT_INTERNAL_CERTIFICATION",
            "producer_domain_id": "PRODUCER",
            "oracle_domain_id": "ORACLE",
            "producer_implementation_sha256": "a" * 64,
            "oracle_implementation_sha256": "a" * 64,
            "credential_scope_ids": ["CRED-P", "CRED-O"],
            "workspace_binding_ids": ["WS-P", "WS-O"],
            "state_store_ids": ["STATE-P", "STATE-O"],
            "parent_task_ids": ["TASK-P", "TASK-O"],
            "blind_input_policy": "MINIMUM_CLAIM_AND_ARTIFACT_ONLY",
            "common_mode_failure_classes": [],
        }
        receipt = evaluate_control_domain(domain)
        self.assertEqual(receipt["independence_decision"], "FAIL_CLOSED")
        self.assertIn("SHARED_VALIDATOR_IMPLEMENTATION", receipt["decision_reason_codes"])

    def test_independent_domain_requires_separate_lineage_facts(self) -> None:
        domain = {
            "claim_id": "CLAIM-CONTROL",
            "assurance_level": "INDEPENDENT_INTERNAL_CERTIFICATION",
            "producer_domain_id": "PRODUCER",
            "oracle_domain_id": "ORACLE",
            "producer_implementation_sha256": "a" * 64,
            "oracle_implementation_sha256": "b" * 64,
            "credential_scope_ids": ["CRED-P", "CRED-O"],
            "workspace_binding_ids": ["WS-P", "WS-O"],
            "state_store_ids": ["STATE-P", "STATE-O"],
            "parent_task_ids": ["TASK-P", "TASK-O"],
            "blind_input_policy": "MINIMUM_CLAIM_AND_ARTIFACT_ONLY",
            "common_mode_failure_classes": [],
        }
        receipt = evaluate_control_domain(domain)
        self.assertEqual(receipt["independence_decision"], "PASS")


if __name__ == "__main__":
    unittest.main()
