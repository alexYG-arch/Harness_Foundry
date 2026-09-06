# Execution startup repair and acceptance

Status: IN_PROGRESS. A bound Execution Root is not a running Harness.

## Current implementation evidence

Steps 1 and 2 are implemented in the Producer, portable action resources and
independent Validator. `tests/test_default_startup_contracts.py` adds ten
regressions using ordinary compilation, including the supported local profile
without historical epoch or private-contract injection. Real temporary startup
actions commit three events, preserve Candidate bytes, and stop with
`next_node=LAB_BOOTSTRAP`, `driver_started=false`, `workpack_started=false`.
The local Candidate also passes its actual portable `tools/self_check.py`.

The 22-test focused run comprising this module, Control Plane Registration and
Program Driver Runtime Verification passed. `verify-spec` and `validate_skill`
passed. The complete 532-test suite passed in 414.408 seconds for the combined
step 1/2 change (2026-09-07). This is Foundry regression evidence, not a target
Harness execution or media acceptance receipt.

Historical self-upgrade negative fixtures reference Foundry-only atoms. They
remain on their original profile, not injected into unrelated target acceptance
cases. Local runtime rejection is tested directly (revocation, expanded probes,
missing executor and skipped Lab); this does not drop the target Requirement's
own acceptance or negative cases.

Step 3 now has a read-only audited decision projection and public CLI. Six
integration tests use actual temporary authoring and validation, preserve the
delegated actor and both existing Candidate identity domains, and prove that the
approval receipt cannot be used as execution authorization. The formal epoch 29
Candidate correctly fails this handoff under the repaired Validator because its
three startup provider artifacts are absent. It has not been modified.

Step 4 has a reproduced and repaired pre-execution freshness gap in the existing
controlled Workpack provider: after hydration, changed control state or changed
executable bytes used to run anyway. The provider now rechecks the already bound
Candidate contracts, live control state and commands before creating output
directories. Producer and independent Validator require this same contract.
Six new regressions cover real local process success, nonzero exit and skipped
verification, both freshness failures, missing contract projection and the
packaged CLI. That CLI used to return exit code 0 even for a provider FAIL; it
now propagates failure to the caller. The old mocked subprocess test is
explicitly named as such.

The process fixture is labeled TEST ONLY and is not Codex. Its tests still use
the historical controlled-Workpack fixture, not the ordinary target's complete
build DAG. They prove process dispatch and failure handling, not real model
generation, isolation certification or normal Harness materialization.

Steps 3–7 remain open: separately scoped human build authority and production
controller integration, generic Workpack execution, fresh Candidate authoring,
Lab/Linkage/Harness execution and target videos are not yet proven.

The combined handoff/freshness/CLI repair passed 20 focused tests in 20.472
seconds and the complete 544-test suite in 442.048 seconds (2026-09-07).
`verify-spec`, `validate_skill.py` and `git diff --check` also passed. The formal
Program stayed at revision 191, `PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`;
this source-validation checkpoint grants no production execution authority.

## Reproduced gap

The normal producer declares `SHARED_CONTROL_BASELINE_LOCK` but previously
omitted its implementation unless the caller injected an optional execution
contract. Registration, Driver probes and the Workpack provider also depend on
historical self-upgrade profiles, epoch numbers and project identifiers. Existing
component tests exercised those enriched fixtures, not the normal public path.

The immutable epoch 29 Candidate is diagnostic input only. Source repair must
not mutate it, manufacture a Human approval, reuse a completed pre-build grant,
or silently skip the Lab and Linkage predecessors in its DAG.

## Serial dependency chain

| Step | Implementation boundary | Required acceptance evidence |
| --- | --- | --- |
| 1 | Emit the existing first control protocol when its DAG node is declared; retain explicit overrides | Normal Candidate compiles without optional-contract injection; real action commits once; independent Validator detects missing/broken bindings |
| 2 | Select registration and Driver-probe providers by the declared route/profile, not historical epoch numbers; derive successor from the actual DAG | Normal Candidate's three startup actions run in an isolated temporary Execution Root; no skipped Lab/Linkage node; Candidate remains unchanged |
| 3 | Bridge audited Factory decisions and a separately scoped human build grant to the runtime | Delegated actor provenance retained; approval is not renamed Human; stale/revoked/absent authority causes no execution writes |
| 4 | Connect production command adapters to the existing transition engine and generalize Workpack hydration | Real commands and their exit status; declared inputs/outputs and write roots; restart/reentry and failure evidence; no test adapter in the production route |
| 5 | Regenerate and review under fresh, correctly scoped authoring authority | New immutable Candidate; no reuse of the completed epoch 29 grant or its output directory |
| 6 | Build Lab, Linkage and target Harness in DAG order | Implemented code, executable acceptance tests and observed results; package-only checks do not satisfy behavioral acceptance |
| 7 | Verify target intent | Three separate approximately 180-second videos, local open-source TTS, local object animation and audio/motion synchronization; truthful source/demo evidence |

## Regression method

At least one test must enter through normal production compilation without
patching Validator/core results or adding private startup contracts to the
Requirement. Component tests remain useful for crash recovery and negative
inputs, but cannot stand in for this test. Production source and its independent
validation change together. Existing digest domains remain distinct; no new
signature service or recursive hashing framework is needed for local self-use.

Run focused tests after each layer, the complete unittest suite after source
changes, and `verify-spec` plus `validate_skill.py` after workflow changes.
Report observed test scope rather than claiming all possible defects eliminated.

## Authority boundaries

The user's request to repair startup and continue building authorizes the
engineering work. Frozen Candidate immutability and completed grant scope still
apply. A new authoring scope/output, external dependency installation, target
Skill invocation, image generation, media generation or release must not be
inferred from a static PASS. Ask only at an actual missing-input or authority
boundary; do not add review gates between deterministic implementation steps.
