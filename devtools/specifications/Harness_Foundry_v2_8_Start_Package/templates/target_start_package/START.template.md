# START: <target-name> Build Program

## 0. Purpose

<Target-specific start purpose and intended outcome.>

## 1. Canonical Inputs

- `canonical_sources/SOURCE_MANIFEST.json`
- `canonical_sources/NORMATIVE_ATOM_CATALOG.json`
- `canonical_sources/ATOM_COVERAGE_MATRIX.json`

## 2. Non-negotiable Meta-rules

```text
PLAN_IS_NOT_EXECUTION
AUTHORING_IS_NOT_WORKPACK_EXECUTION
PACK_IS_NOT_CERTIFICATE
LINKAGE_PASS_IS_NOT_CERTIFICATION_PASS
P4_REQUIRES_CURRENT_P3_LOCK_AND_C3_PASS
SELF_REPORTED_RUNTIME_RECEIPT_IS_NOT_ATTESTATION
BUILD_PROGRAM_DRIVER_IS_NOT_FINAL_HARNESS_RUNTIME
INSTALLED_RUNTIME_MUST_NOT_RESOLVE_TO_SOURCE_OR_BUILD_PROGRAM
AUTO_PROGRESS_REQUIRES_VALID_AUTHORIZATION
NEXT_ACTION_MUST_BE_UNIQUE
REAL_TARGET_INSTALL_REQUIRES_SEPARATE_AUTHORIZATION
```

## 3. Initial Program State

Read `PROGRAM_STATE.json`, `PHASE_DEPENDENCY_MANIFEST.json` and `PROGRAM_DRIVER_STATE.json`. The current activity is `BUILD_PROGRAM_AUTHORING`, while the only current execution mode is `AUTHORING_ONLY`; generated commands remain `DECLARE_ONLY`.

## 4. First Authorized Future Workpack

- Candidate Workpack: `<WP-G0-ID>`
- Activation requires: `<CHARTER/PROFILE/START-GATE-EVIDENCE>`
- This document does not activate it.

## 5. Authoring Stop

Stop after producing `AUTHORING_HANDOFF.md`. Do not begin Coding until the human authority approves the required locks and separately authorizes execution.

## 6. Authorized Future Progression

After approval and Registration, the Driver may follow `ENGINEERING_PROJECT_DAG.json` and `RELEASE_PIPELINE_MANIFEST.json` only within a valid `EXECUTION_AUTHORIZATION`. It must stop on every hard gate defined by `PROGRAM_AUTOMATION_POLICY.json` and `AUTHORIZATION_POLICY.json`.
