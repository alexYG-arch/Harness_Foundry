# Harness Foundry v2.9 v0_32 Human Review

## Review decision

`FAIL — REOPEN_REQUIRED`

This was a read-only Human Review of the published v0_32 Candidate. It did not
approve or consume a Human Gate, create an Execution Root, start a Driver or
Workpack, grant authority, or execute a runtime transition. The v0_32 Candidate
is retained as immutable historical evidence.

## Reviewed identity

- Program: `PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE`
- Candidate: `candidate-v0_32`
- Candidate content SHA-256: `c4f1a7fb1bd852d1a77b033f5728a0bc16f90c36bc884a57ca1131f64886db18`
- Candidate file count: `344`
- Source Requirement IR SHA-256: `288831725d421615c5a74fd8fb4860b3d7ca42fdc7371cb7d042e9fad3ee0b34`
- Requirement Epoch: `32`
- Review input Factory revision: `249`
- Review input Factory state SHA-256: `2ddac7e4c4d66bc0787d87d83d0105326ac5fdd0c29fde3d034339477c845d6c`

## Blocking findings

### HR-V032-001 — Runtime Binder preflight is incomplete

`tools/setup_runtime.py` validates the portable inventory and Resource URIs
before publishing a fresh Execution Root, but it does not independently check
the packaged Python relative-import dependency closure or the receiver-side
authority prerequisites before the first Execution Root write. A Candidate can
therefore pass the Binder's narrow preflight while still being unusable or
untrusted at runtime.

### HR-V032-002 — Epoch 32 adversarial cases are assigned to the wrong domain

The four Epoch 32 cases for dangling Candidate URIs, files outside the portable
inventory, missing packaged relative imports, and failure leaving a fresh Root
absent are Runtime Binder/portability responsibilities. v0_32 incorrectly
publishes them under `source_authority_required_adversarial_cases`. This makes
the release manifest describe the wrong owner and can hide missing Binder
coverage behind unrelated Source Authority checks.

### HR-V032-003 — Closure does not bind the actual Binder implementation

The Epoch 32 Closure Receipt reports PASS without including
`tools/setup_runtime.py` in its evidence references or Hash map. The Runtime
Binding Contract also lacks the exact setup script Hash and explicit fields for
pre-write validation, same-parent staging, atomic publication, cleanup, and
Human Gate non-consumption. The declared closure therefore does not prove the
implementation that performs the binding.

### HR-V032-004 — missing Authority produces a dependent false finding

When receiver-side Source Authority inputs are absent, standalone correctly
reports `SOURCE_AUTHORITY_POLICY_LOCK_REQUIRED`, but then also reports
`V2_9_EPOCH24_GATE_ADVERSARIAL_CASES_INVALID`. The second result is not an
independent defect; it is a cascade caused by running an authority-dependent
attack after its prerequisite is unavailable. The root cause must be preserved
without the misleading dependent finding.

## Required replacement closure

The v0_33 replacement must:

1. run portable-manifest, all Candidate URI, runtime relative-import dependency
   closure, Binder implementation Hash/atomicity, and necessary receiver
   authority checks before the first Execution Root write;
2. publish the four Epoch 32 URI/Binder attacks only in a dedicated Runtime
   Binder adversarial domain and exclude them from Source Authority;
3. bind the exact `tools/setup_runtime.py` SHA-256 and atomicity fields in both
   `validation/RUNTIME_BINDING_CONTRACT.json` and the Human Review Closure
   Receipt;
4. keep a fresh Execution Root absent on every failed preflight and never
   consume Human Gate authority before successful binding;
5. suppress authority-dependent cascade findings when the external Authority
   prerequisite is missing, while preserving the root-cause finding;
6. route this Requirement through Producer, Factory Validator and standalone
   self-check, with independent regression coverage;
7. preserve v0_32 and this review evidence without runtime side effects.

