# Harness Foundry versioned source layout

The repository root preserves the original
`Harness_Foundry_v2_8_Chat_Factory_v0_1` source tree. It is retained as
read-only history and is not migrated in place.

## Current packages

- `Harness_Foundry_v2_8_Chat_Factory_v0_2/`
  - Statically compiles and validates Agent, Harness, and Hybrid Start Package
    candidates.
  - Stops at `START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW`.
  - Exports only hash-bound execution handoff descriptions.
- `Harness_Foundry_v2_8_Controlled_Execution_Runtime_v0_1/`
  - Provides the independent `hfdriver` runtime for bootstrap, authorization,
    Workpack advancement, recovery, and read-only migration planning.
  - Defaults to `A1_PLAN_ONLY`; A3 execution requires a separate bounded
    authorization after Driver verification.

Runtime roots, SQLite event stores, generated candidates, caches, virtual
environments, and in-progress execution artifacts are intentionally excluded
from this source publication.

Factory validation expects the locked, read-only normative package at
`<repository-root>/Harness_Foundry_v2_8_Start_Package`. That package is an
external input and is not duplicated in this repository.
