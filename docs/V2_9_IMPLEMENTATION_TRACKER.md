# Harness Foundry v2.9 Implementation Tracker

Status: `CORE_PRODUCT_IMPLEMENTED_VALIDATED_AND_PORTABLE`

Active delivery profile: `SELF_USE_LOCAL_TRUSTED_OPERATOR`

The active tracker covers the local Foundry engineering product. Candidate generation and sibling Runtime construction are optional compatibility extensions, not core completion gates. The superseded Epoch 9 tracker is preserved in [`archive/V2_9_IMPLEMENTATION_TRACKER_EPOCH9_ARCHIVE.md`](archive/V2_9_IMPLEMENTATION_TRACKER_EPOCH9_ARCHIVE.md).

| Delivery tier | Scope | State | Completion evidence |
|---|---|---|---|
| `CORE_IMPLEMENTATION` | Product identity and CLI | `COMPLETE` | `version` and machine-readable product identity |
| `CORE_IMPLEMENTATION` | Requirement/Architecture readback, locks and compile | `COMPLETE` | Explicit Hash-bound dual lock and read-only compiled contract |
| `CORE_IMPLEMENTATION` | Profile graph, rule evaluator and generic transition engine | `COMPLETE` | Data-driven topology with one shared engine |
| `CORE_IMPLEMENTATION` | Authoring and bounded runtime advance | `COMPLETE` | Typed real-gate stops, parent-scope narrowing and idempotency |
| `CORE_IMPLEMENTATION` | Checkpoint, Resume and Explain Stop | `COMPLETE` | Durable event-bound recovery without replaying committed effects |
| `CORE_IMPLEMENTATION` | Portable local package and startup | `COMPLETE` | Logical roots, containment, dependency discovery and diagnostic self-check |
| `POST_IMPLEMENTATION_VALIDATION` | Core behavior and evidence projection | `COMPLETE` | 41 behavior-bound capabilities, 17 failure paths, 26 exact selectors, 278-test regression, deterministic evidence projection |
| `OPTIONAL_COMPATIBILITY` | Candidate generation and local release-ready gate | `IMPLEMENTED_NONDEFAULT_NOT_RUN` | Preserved implementation; excluded from default route and core validation |
| `OPTIONAL_COMPATIBILITY` | Control registration, Driver verification and Workpack Runtime | `IMPLEMENTED_NONDEFAULT_NOT_RUN` | Preserved implementation; no Execution Root, A3, Driver or Workpack required for core completion |
| `OPTIONAL_COMPATIBILITY` | Main execution package structural validation | `IMPLEMENTED_NONDEFAULT_NOT_RUN` | Preserved implementation; nonblocking for local Foundry delivery |
| `OPTIONAL_SECURITY_HARDENING` | External Trust Anchor, independent certification and dynamic adversarial work | `NOT_RUN_NOT_REQUIRED` | External certification remains false |

## Active completion rule

Foundry v2.9 core is complete when all of the following are true:

1. The 41 declared core capabilities bind to real modules, public entrypoints and exact tests.
2. Official core validation passes without creating Candidate or Execution roots.
3. A temporary relocated local package passes version and diagnostic startup smoke.
4. External certification remains false and optional security hardening remains `NOT_RUN`.

## Non-goals for core closure

- No Requirement reopen, Candidate generation, Human Gate or Runtime Bind.
- No Execution Root, A3, Program Driver or Workpack execution.
- No dynamic adversarial reproduction or optional security hardening.
- No target installation, publication or external certification claim.

## Slice 15 completion evidence

- Official core validation: `PASS`; SHA-256 `ddc49e3985dd54ea975f8515cca45c1bad8fafe3f1431742ec6f870e2519bb55`.
- Product Manifest: SHA-256 `f09488e536b1d060b0e77a0dffbdae34e53d05e14d5c39883ce7df74c40ac842`.
- Core evidence projection: `PASS`; SHA-256 `ce6ec07d7a518307dadf8279ca91ef2681a1384702779d0488e508fc06ea862b`.
- Full local regression: `278 tests`, `OK`; `PYTHONWARNINGS=always::ResourceWarning` reported zero resource warnings.
- Relocated local package: `47 files`; version and diagnostic startup smoke `PASS`; network and editable install not used.
- Optional compatibility: 8 capabilities preserved, `NOT_RUN`, `default_route=false`, `core_release_blocking=false`.
- Slice 15A test hygiene: three test-only SQLite connections now close explicitly; the exact two-test warning regression passed without changing production code, capability counts, validation scope, validation SHA or evidence-projection SHA.
