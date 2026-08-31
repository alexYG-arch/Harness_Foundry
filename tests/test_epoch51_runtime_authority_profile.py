"""Slice 14 profile-aware runtime-Authority regression tests.

These tests exercise pure profile decisions, non-executable JSON fixtures, and
the generated binder's prewrite ordering. They do not create or execute a
Candidate or Execution Root.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from harness_foundry_factory.compiler import (
    _epoch51_runtime_authority_negative_cases,
    _external_receiver_authority_disposition,
    _external_receiver_authority_required,
    _local_profile_external_authority_not_applicable,
    _write_runtime_binding_support,
)
from harness_foundry_factory.validator import (
    _external_receiver_authority_disposition as validator_disposition,
    _external_receiver_authority_required as validator_authority_required,
    _is_nonexecutable_negative_fixture,
    _local_profile_external_authority_not_applicable as validator_local_na,
)


def _target() -> dict:
    return {
        "architecture_epoch": 4,
        "control_plane_epoch": 4,
        "assurance_profile_id": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "operating_assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "v0_24_human_review_remediation": {"status": "HISTORICAL"},
        "v2_9_charter_architecture_correction_epoch38": {
            "threat_model": {
                "external_trust_anchor": "NOT_APPLICABLE",
                "external_certification_offered": False,
            }
        },
    }


def _profile() -> dict:
    return {
        "profile_kind": "SELF_USE_LOCAL_CORE_CANDIDATE_ROUTE",
        "assurance_profile": "SELF_USE_LOCAL_TRUSTED_OPERATOR",
        "external_certification_claimed": False,
        "optional_security_hardening": "NOT_RUN",
        "external_trust_anchor": "NOT_APPLICABLE",
    }


class Epoch51RuntimeAuthorityProfileTests(unittest.TestCase):
    def _assert_profile_decision(
        self,
        profile: dict,
        *,
        local_na: bool,
        authority_required: bool,
        disposition: str,
    ) -> None:
        root = Path("/nonexecuting-profile-fixture")
        serialized = json.dumps(profile)
        target = _target()
        with patch.object(Path, "read_text", return_value=serialized):
            self.assertIs(
                _local_profile_external_authority_not_applicable(root, target),
                local_na,
            )
            self.assertIs(
                _external_receiver_authority_required(root, target),
                authority_required,
            )
            self.assertEqual(
                _external_receiver_authority_disposition(root, target),
                disposition,
            )
            self.assertIs(validator_local_na(root, target), local_na)
            self.assertIs(
                validator_authority_required(root, target),
                authority_required,
            )
            self.assertEqual(
                validator_disposition(root, target),
                disposition,
            )

    def test_local_profile_makes_external_authority_not_applicable(self) -> None:
        self._assert_profile_decision(
            _profile(),
            local_na=True,
            authority_required=False,
            disposition="NOT_APPLICABLE_SELF_USE_LOCAL_TRUSTED_OPERATOR",
        )

    def test_external_claim_or_optional_hardening_fails_closed(self) -> None:
        external_claim = _profile()
        external_claim["external_certification_claimed"] = True
        self._assert_profile_decision(
            external_claim,
            local_na=False,
            authority_required=True,
            disposition="REQUIRED_FOR_EXTERNAL_CERTIFICATION",
        )

        optional_hardening = _profile()
        optional_hardening["optional_security_hardening"] = "ENABLED"
        self._assert_profile_decision(
            optional_hardening,
            local_na=False,
            authority_required=True,
            disposition="REQUIRED_FOR_EXTERNAL_CERTIFICATION",
        )

    def test_negative_cases_are_nonexecutable_json_fixtures(self) -> None:
        cases = _epoch51_runtime_authority_negative_cases()
        self.assertEqual(
            {case["case_id"] for case in cases},
            {
                "NEG-V29-E51-LOCAL-RUNTIME-AUTHORITY-CLAIM-DRIFT",
                "NEG-V29-E51-OPTIONAL-HARDENING-AUTHORITY-OMISSION",
            },
        )
        self.assertTrue(all(_is_nonexecutable_negative_fixture(case) for case in cases))

    def test_runtime_bind_validates_before_first_staging_write(self) -> None:
        source = inspect.getsource(_write_runtime_binding_support)
        self.assertLess(
            source.index("validate_receiver_authority(candidate)"),
            source.index("tempfile.mkdtemp("),
        )
        self.assertIn('"receiver_authority_preflight_mode": "PROFILE_AWARE"', source)


if __name__ == "__main__":
    unittest.main()
