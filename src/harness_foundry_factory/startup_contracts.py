"""Production defaults for required startup actions, independent of fixtures.

The shared registration contract is the existing v0.9 wire protocol promoted
from its historical test-only configuration. It does not grant authority or
change a frozen Requirement. Explicit overrides remain exact and validated.
"""

from copy import deepcopy
import json


_SHARED_CONTROL_DEFAULT = json.loads(r'''
{
  "execution_contract": {
    "action_contract_ref": "validation/SHARED_CONTROL_BASELINE_ACTION_CONTRACT.json",
    "action_id": "DERIVE-AND-LOCK-SHARED-CONTROL-BASELINE",
    "action_kind": "DETERMINISTIC_PEP_CONTROL_ACTION",
    "allowed_write_roots": [
      "harness-resource://execution/evidence/engineering_dag/SHARED_CONTROL_BASELINE_LOCK"
    ],
    "contract_id": "SHARED-CONTROL-BASELINE-EXECUTION-CONTRACT-V1",
    "determinism_contract": {
      "baseline_identity_inputs_exactly_declared": true,
      "canonical_json": true,
      "environment_allowlist": {},
      "hash_algorithm": "SHA256",
      "network": "DENY",
      "shell": false,
      "wall_clock_excluded_from_baseline_identity": true
    },
    "executor_hash_binding": {
      "implementation_hash_required_in_action_contract": true,
      "implementation_hash_required_in_authorization": true,
      "implementation_hash_required_in_command_manifest": true,
      "implementation_hash_required_in_result": true,
      "missing_or_mismatched_failure_code": "UNBOUND_OR_DRIFTED_CONTROL_ACTION_IMPLEMENTATION",
      "portable_manifest_must_bind_implementation_file": true,
      "post_readback_implementation_change_invalidates_authorization": true
    },
    "implementation_ref": "tools/shared_control_baseline.py",
    "node_id": "SHARED_CONTROL_BASELINE_LOCK",
    "pep_internal_write_roots": [
      "harness-resource://execution/.harness-foundry/control"
    ],
    "produced_capabilities": [
      "SHARED_CONTROL_BASELINE_LOCK_PASS",
      "CHARTER_LOCK_VALID",
      "SHARED_PROTOCOL_LOCK_VALID"
    ],
    "recovery_contract": {
      "crash_points": [
        "AFTER_PREPARE_BEFORE_RESULT_RENAME",
        "AFTER_RESULT_RENAME_BEFORE_EVENT_APPEND",
        "AFTER_EVENT_APPEND_BEFORE_STATE_REPLACE",
        "AFTER_STATE_REPLACE_BEFORE_RESPONSE"
      ],
      "partial_state_must_reconcile_or_fail_closed": true,
      "recovery_receipt_required": true,
      "resume_never_replays_committed_side_effect": true,
      "resume_revalidates_candidate_authorization_and_hashes": true
    },
    "required_inputs": [
      "harness-resource://candidate/PROGRAM_CHARTER.md",
      "harness-resource://candidate/CHARTER_LOCK.json",
      "harness-resource://candidate/PROFILE_LOCK.json",
      "harness-resource://candidate/AUTHORIZATION_POLICY.json",
      "harness-resource://candidate/THREE_PROJECT_PROGRAM_MANIFEST.json",
      "harness-resource://candidate/build_program/conformance/CONFORMANCE_INTERFACE.json",
      "harness-resource://candidate/constitution/RUNTIME_ATTESTATION_POLICY.json",
      "harness-resource://candidate/canonical_sources/NORMATIVE_ATOM_CATALOG.json",
      "harness-resource://candidate/canonical_sources/SOURCE_MANIFEST.json",
      "harness-resource://execution/evidence/engineering_dag/START_PACKAGE_HUMAN_APPROVAL/result.json"
    ],
    "required_result_fields": [
      "schema_version",
      "result_id",
      "program_id",
      "node_id",
      "status",
      "execution_mode",
      "control_plane_epoch",
      "candidate_tree_sha256",
      "requirement_ir_sha256",
      "charter_sha256",
      "profile_lock_sha256",
      "authorization_policy_sha256",
      "shared_protocol_sha256",
      "schema_bundle_sha256",
      "normative_atom_catalog_sha256",
      "source_manifest_sha256",
      "human_approval_receipt_sha256",
      "command_manifest_sha256",
      "executor_implementation_sha256",
      "authorization_id",
      "authorization_sha256",
      "idempotency_key",
      "lease_id",
      "fencing_token",
      "produced_capabilities",
      "started_at",
      "completed_at",
      "result_sha256"
    ],
    "result_ref": "harness-resource://execution/evidence/engineering_dag/SHARED_CONTROL_BASELINE_LOCK/result.json",
    "result_schema_ref": "contracts/SHARED_CONTROL_BASELINE_RESULT.schema.json",
    "scope_and_nonclaims": {
      "automatic_successor_advance_allowed": false,
      "driver_start_allowed": false,
      "max_loop_iterations": 0,
      "max_transitions": 1,
      "registration_only": true,
      "runtime_harness_completion_claimed": false,
      "target_install_allowed": false,
      "workpack_execution_allowed": false
    },
    "transaction_contract": {
      "different_idempotency_key_after_completion_rejected": true,
      "duplicate_same_idempotency_key_returns_existing_receipt": true,
      "event_and_state_hash_chain_required": true,
      "idempotency_key_required": true,
      "lease_id_required": true,
      "monotonic_fencing_token_required": true,
      "pass_not_observable_before_result_and_control_state_reconcile": true,
      "result_temp_write_then_fsync_then_atomic_replace": true,
      "transaction_journal_required": true,
      "transaction_states": [
        "PREPARED",
        "RESULT_COMMITTED",
        "CONTROL_EVENT_COMMITTED",
        "STATE_COMMITTED"
      ],
      "unknown_commit_state_requires_reconciliation_before_retry": true
    }
  },
  "test_contract": {
    "all_declared_crash_points_tested": true,
    "duplicate_idempotency_test_required": true,
    "executor_hash_mismatch_test_required": true,
    "fencing_token_regression_test_required": true,
    "post_crash_resume_no_duplicate_event_or_result": true,
    "producer_success_test_required": true,
    "result_schema_validation_test_required": true,
    "revoked_authorization_reuse_test_required": true,
    "tests_must_execute_real_candidate_action_in_temporary_isolated_roots": true,
    "validator_only_closure_forbidden": true
  }
}
''')


def shared_control_default():
    """Return fresh production protocol data, never test or caller state."""
    return deepcopy(_SHARED_CONTROL_DEFAULT)
