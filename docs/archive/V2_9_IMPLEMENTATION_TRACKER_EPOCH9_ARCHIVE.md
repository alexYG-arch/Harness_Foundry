# Harness Foundry v2.9 Implementation Tracker — Epoch 9 Archive

Archive status: `HISTORICAL_NOT_ACTIVE`

This file preserves the superseded Epoch 9 tracker verbatim below. It is not a current implementation or delivery authority.

---

# Harness Foundry v2.9 Implementation Tracker

Status: `PHASE_00_COMPLETE_PHASE_01_REQUIREMENT_EPOCH9_AUTHORING_IN_PROGRESS`

This tracker separates documents, implementation, execution evidence and certification. A checked planning row is not runtime proof.

| Phase | Scope | Current state | Completion evidence |
|---|---|---|---|
| `P29-00` | Isolated repository and source import | `COMPLETE` | Independent Git/root, physical read-only sibling, no copied runs/SQLite, verify-spec PASS, Skill PASS, 80 tests PASS |
| `P29-01` | Requirement Epoch 9 Architecture Correction Readback | `IN_PROGRESS` | Same v2.9 Program reopened 8→9; revision 64; v0.10 output root and correction source bound; Slice A proposals prepared; Factory Readback not yet frozen |
| `P29-01A` | Slice A baseline and Architecture Decision Packet | `PROPOSAL_READY_NOT_FROZEN` | `BASELINE_REUSE_MANIFEST`, `HUMAN_COST_BASELINE`, Assurance/Control-Domain/Decision-Policy proposal schemas and one Architecture Decision Packet |
| `P29-02` | Requirement and Architecture dual lock | `PENDING` | Schemas, state transitions, negative tests, exact later human freeze |
| `P29-03` | Complete Charter Clause disposition and enforcement | `PENDING` | Clause coverage, Policy IR, enforcement points, receipts and invalidation |
| `P29-04` | Authoring advance-until-gate | `PENDING` | One combined command reaches only a true human/authoring gate |
| `P29-05` | Parent Authorization and Derived Attempt Bundle | `PENDING` | No manual child Hash; scope/risk expansion returns to human |
| `P29-06` | Runtime advance-until-gate | `PENDING` | Bounded automatic DAG progress with no per-node human prompt |
| `P29-07` | Checkpoint and Resume | `PENDING` | Process/budget interruption recovery and unknown-side-effect hard stop |
| `P29-08` | Evidence applicability and independent closure | `PENDING` | Requirement-specific evidence, Oracle independence and false-closure tests |
| `P29-09` | Portable generation and release contract | `PENDING` | Candidate/Frozen IR/manifests use logical refs; runtime rebinds locally; clean clone, second random root, environment/tool/plugin manifest and zero exported local binding |
| `P29-10` | Non-origin profile and compatibility | `PENDING` | At least one unrelated Target Profile and v2.8 compatibility evidence |
| `P29-11` | v2.9 release candidate | `PENDING` | P0-01 through P0-10 implemented, tested, read back and independently certified |

## Hard rules

- The current source import can prove only the v2.8 compatibility baseline.
- No Phase moves to `COMPLETE` from documentation alone.
- Generated Workpacks remain `PLANNED_NOT_STARTED` until separately authorized outside Factory Authoring.
- A structural Candidate PASS is not P0-10 evidence while generated files still contain author-machine paths.
- Local SQLite may retain resumable bindings, but it is non-exportable; portable Candidate and release artifacts must not copy them.
- Freeze confirmation is never submitted from the same user message that requests a token.
- v3.0 capabilities remain out of the v2.9 critical path.
- Requirement Epoch 9 reuses this already-independent v2.9 Program history; it does not reopen or reuse the v2.8 Program/SQLite.
- `P29-01A` documents are authoring proposals only. They cannot become implementation evidence until a later exact Architecture Freeze and executable tests.
