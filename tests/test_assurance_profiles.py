"""Unit tests for risk-scoped Start Package assurance profiles."""

from __future__ import annotations

import unittest

from harness_foundry_factory.assurance_profiles import (
    AUTHORING_LOCAL,
    DISTRIBUTED_RELEASE_ADVERSARIAL,
    LEGACY_SELF_USE_LOCAL_TRUSTED_OPERATOR,
    LOCAL_EXEC_UNTRUSTED_INPUT,
    UnknownAssuranceProfileError,
    UnknownHF28NegativeCaseError,
    assurance_profile_for_start_package,
    filter_hf28_negative_case_ids,
    filter_hf28_negative_case_specs,
    hf28_negative_case_routes,
    is_hf28_negative_case_applicable,
    normalize_assurance_profile,
    resolve_assurance_profile,
    resolve_hf28_negative_case_route,
)
from harness_foundry_factory.semantic_contracts import (
    HF28_MANDATORY_NEGATIVE_CASE_SPECS,
    negative_case_specs_with_mandatory_controls,
)


class AssuranceProfileTests(unittest.TestCase):
    def test_start_package_personal_local_routes_to_untrusted_input_profile(self) -> None:
        requirement_ir = {
            "target": {
                "start_package_immutability_policy": {
                    "physical_permission_enforcement": "BEST_EFFORT_PERSONAL_LOCAL"
                }
            }
        }
        self.assertEqual(
            assurance_profile_for_start_package(requirement_ir).profile_id,
            LOCAL_EXEC_UNTRUSTED_INPUT,
        )

    def test_unspecified_start_package_profile_preserves_release_controls(self) -> None:
        self.assertEqual(
            assurance_profile_for_start_package({}).profile_id,
            DISTRIBUTED_RELEASE_ADVERSARIAL,
        )

    def test_semantic_negative_cases_use_resolved_profile(self) -> None:
        requirement_ir = {
            "atoms": [{"atom_id": "ATOM-1"}],
            "negative_cases": [],
            "target": {
                "start_package_immutability_policy": {
                    "physical_permission_enforcement": "BEST_EFFORT_PERSONAL_LOCAL"
                }
            },
        }
        cases = negative_case_specs_with_mandatory_controls(requirement_ir)
        case_ids = {case["case_id"] for case in cases}
        self.assertIn("NEG-HF28-CODEX-SELF-REPORT", case_ids)
        self.assertNotIn("NEG-HF28-ATTESTATION-REPLAY", case_ids)
        self.assertNotIn("NEG-HF28-THREE-PROJECT-ORDER", case_ids)
        self.assertTrue(
            all(
                case["assurance_profile"] == LOCAL_EXEC_UNTRUSTED_INPUT
                for case in cases
            )
        )

    def test_normalize_accepts_canonical_case_and_separator_variants(self) -> None:
        self.assertEqual(
            normalize_assurance_profile("  authoring-local "), AUTHORING_LOCAL
        )
        self.assertEqual(
            normalize_assurance_profile("local_exec_untrusted_input"),
            LOCAL_EXEC_UNTRUSTED_INPUT,
        )

    def test_legacy_self_use_profile_maps_to_bounded_local_execution(self) -> None:
        self.assertEqual(
            normalize_assurance_profile(LEGACY_SELF_USE_LOCAL_TRUSTED_OPERATOR),
            LOCAL_EXEC_UNTRUSTED_INPUT,
        )
        self.assertEqual(
            resolve_assurance_profile(LEGACY_SELF_USE_LOCAL_TRUSTED_OPERATOR),
            resolve_assurance_profile(LOCAL_EXEC_UNTRUSTED_INPUT),
        )

    def test_unknown_or_empty_profile_fails_closed(self) -> None:
        for value in (None, "", "   ", "UNSCOPED", 3):
            with self.subTest(value=value):
                with self.assertRaises(UnknownAssuranceProfileError):
                    resolve_assurance_profile(value)

    def test_profiles_are_cumulative_and_keep_local_boundaries(self) -> None:
        authoring = resolve_assurance_profile(AUTHORING_LOCAL)
        local_exec = resolve_assurance_profile(LOCAL_EXEC_UNTRUSTED_INPUT)
        release = resolve_assurance_profile(DISTRIBUTED_RELEASE_ADVERSARIAL)

        self.assertLess(authoring.level, local_exec.level)
        self.assertLess(local_exec.level, release.level)
        self.assertTrue(set(authoring.controls).issubset(local_exec.controls))
        self.assertTrue(set(local_exec.controls).issubset(release.controls))
        self.assertIn("OUTPUT_ROOT_CONFINEMENT", authoring.controls)
        self.assertIn("EXACT_SCOPE_AUTHORIZATION", authoring.controls)
        self.assertIn("NETWORK_EGRESS_DENY_BY_DEFAULT", local_exec.controls)
        self.assertIn("AUTOMATIC_INSTALL_DENIED", local_exec.controls)
        self.assertIn("ONE_JOB_READ_WRITE_LEASE", local_exec.controls)
        self.assertIn(
            "SIDE_EFFECT_IDEMPOTENCY_AND_RECONCILIATION", local_exec.controls
        )
        self.assertNotIn("ATTESTATION_REPLAY_PROTECTION", local_exec.controls)
        self.assertIn("ATTESTATION_REPLAY_PROTECTION", release.controls)
        self.assertIn("THREE_PROJECT_RELEASE_ORDER", release.controls)
        self.assertIn("TOOL_DISTRIBUTION_INTEGRITY", release.controls)
        self.assertIn("SINGLE_ACTIVE_WORKPACK_ACROSS_PROJECTS", release.controls)

    def test_route_catalog_covers_every_existing_hf28_case_exactly(self) -> None:
        expected = {spec[0] for spec in HF28_MANDATORY_NEGATIVE_CASE_SPECS}
        routes = hf28_negative_case_routes()
        self.assertEqual({route.case_id for route in routes}, expected)
        self.assertEqual(len(routes), len(expected))

    def test_every_route_has_rationale_control_and_failure_action(self) -> None:
        failures = {
            case_id: expected_failure
            for case_id, _description, expected_failure
            in HF28_MANDATORY_NEGATIVE_CASE_SPECS
        }
        for route in hf28_negative_case_routes():
            with self.subTest(case_id=route.case_id):
                self.assertIn(
                    route.minimum_profile,
                    {
                        AUTHORING_LOCAL,
                        LOCAL_EXEC_UNTRUSTED_INPUT,
                        DISTRIBUTED_RELEASE_ADVERSARIAL,
                    },
                )
                self.assertTrue(route.control_id)
                self.assertGreaterEqual(len(route.rationale.split()), 5)
                self.assertEqual(route.failure_action, failures[route.case_id])

    def test_authoring_profile_keeps_only_authoring_applicable_cases(self) -> None:
        selected = filter_hf28_negative_case_specs(
            HF28_MANDATORY_NEGATIVE_CASE_SPECS, AUTHORING_LOCAL
        )
        self.assertEqual(
            {spec[0] for spec in selected},
            {"NEG-HF28-STALE-HASH", "NEG-HF28-AUTH-SCOPE"},
        )

    def test_local_execution_adds_execution_not_release_cases(self) -> None:
        selected = {
            spec[0]
            for spec in filter_hf28_negative_case_specs(
                HF28_MANDATORY_NEGATIVE_CASE_SPECS,
                LOCAL_EXEC_UNTRUSTED_INPUT,
            )
        }
        self.assertIn("NEG-HF28-CODEX-SELF-REPORT", selected)
        self.assertIn("NEG-HF28-OUTPUT-SUBSTITUTION", selected)
        self.assertIn("NEG-HF28-AUTO-REAL-INSTALL", selected)
        self.assertIn("NEG-HF28-MULTIPLE-NEXT-LEASE", selected)
        self.assertIn("NEG-HF28-CRASH-DUPLICATE", selected)
        self.assertNotIn("NEG-HF28-ATTESTATION-REPLAY", selected)
        self.assertNotIn("NEG-HF28-CERTIFICATE-REUSE", selected)
        self.assertNotIn("NEG-HF28-THREE-PROJECT-ORDER", selected)
        self.assertNotIn("NEG-HF28-TOOL-DISTRIBUTION-DRIFT", selected)
        self.assertNotIn("NEG-HF28-DUAL-ACTIVE-WORKPACK", selected)

    def test_distributed_release_enables_all_existing_hf28_cases(self) -> None:
        selected = filter_hf28_negative_case_specs(
            HF28_MANDATORY_NEGATIVE_CASE_SPECS,
            DISTRIBUTED_RELEASE_ADVERSARIAL,
        )
        self.assertEqual(selected, HF28_MANDATORY_NEGATIVE_CASE_SPECS)

    def test_filter_ids_preserves_order_and_does_not_mutate_input(self) -> None:
        case_ids = [
            "NEG-HF28-ATTESTATION-REPLAY",
            "NEG-HF28-AUTH-SCOPE",
            "NEG-HF28-CRASH-DUPLICATE",
        ]
        original = list(case_ids)
        self.assertEqual(
            filter_hf28_negative_case_ids(case_ids, LOCAL_EXEC_UNTRUSTED_INPUT),
            ("NEG-HF28-AUTH-SCOPE", "NEG-HF28-CRASH-DUPLICATE"),
        )
        self.assertEqual(case_ids, original)

    def test_mapping_specs_are_supported_and_preserve_identity(self) -> None:
        authoring = {"case_id": "NEG-HF28-AUTH-SCOPE"}
        release = {"case_id": "NEG-HF28-CERTIFICATE-REUSE"}
        selected = filter_hf28_negative_case_specs(
            (authoring, release), AUTHORING_LOCAL
        )
        self.assertEqual(selected, (authoring,))
        self.assertIs(selected[0], authoring)

    def test_unknown_case_and_malformed_spec_fail_closed(self) -> None:
        with self.assertRaises(UnknownHF28NegativeCaseError):
            resolve_hf28_negative_case_route("NEG-HF28-NEW-UNKNOWN")
        with self.assertRaises(UnknownHF28NegativeCaseError):
            filter_hf28_negative_case_specs(({},), AUTHORING_LOCAL)
        with self.assertRaises(UnknownHF28NegativeCaseError):
            filter_hf28_negative_case_specs(((),), AUTHORING_LOCAL)

    def test_applicability_is_cumulative(self) -> None:
        case_id = "NEG-HF28-ATTESTATION-REPLAY"
        self.assertFalse(is_hf28_negative_case_applicable(case_id, AUTHORING_LOCAL))
        self.assertFalse(
            is_hf28_negative_case_applicable(
                case_id, LEGACY_SELF_USE_LOCAL_TRUSTED_OPERATOR
            )
        )
        self.assertTrue(
            is_hf28_negative_case_applicable(
                case_id, DISTRIBUTED_RELEASE_ADVERSARIAL
            )
        )


if __name__ == "__main__":
    unittest.main()
