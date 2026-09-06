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

### Ordinary-project Workpack routing

The normal local profile now packages the materialization provider without a
Foundry-only target ID or historical epoch threshold. The provider reads its
Workpack ID, command/capsule refs and actual predecessor from the Candidate DAG
and index. A second ordinary project at Requirement epoch 73 no longer gets
misclassified as a historical self-upgrade validation profile. The independent
Validator still requires the normal provider and its exact projections.

The same module exposes a read-only `plan --candidate-root ... --node-id ...`
command. It resolves ordered root/project Workpacks and retains complete command
contracts, native task bundles and Job lease fields. It creates no directories,
grants no authorization and is not execution. A read-only check of the actual
epoch 29 Candidate resolved its 10 Workpack-bearing engineering nodes into 13
ordered Workpacks, with all Candidate bytes unchanged. This covers that
engineering DAG, not additional release-pipeline Workpacks.

Normal compilation tests use no compiler/Validator mocks. They exercise the
packaged plan CLI, project/Workpack binding failures, the real three startup
actions stopping before Lab, and a real local process through the ordinary Main
materialization provider. The last test uses explicit test-only predecessor and
process fixtures; it does not claim that Lab, Linkage or Codex have run.

The packaged CLI test removes the test suite's bytecode environment variable
and uses a physically writable temporary Candidate copy. It reproduced import
cache writes that broke the portable inventory check. The entrypoint now
disables bytecode writes before loading its provider; the same test checks the
entire temporary tree remains unchanged. Permission modes are not relied on to
make a read-only command read-only.

This slice passed 40 focused tests in 27.374 seconds and the full 554-test suite
in 442.978 seconds (2026-09-07). `verify-spec`, `validate_skill.py` and
`git diff --check` passed. A fresh read-only check of the formal Program still
reported revision 191, `PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`; its existing
Execution Root contains only the runtime binding file. No formal execution or
Candidate lifecycle transition occurred during this source repair.

This removes the root provider's self-upgrade identity/predecessor coupling.
Executing Lab/Linkage/project Workpack sequences and connecting production
adapters to the authoritative controller remain open. Neither a declared plan
nor a structural Main package closes the target's behavioral/media acceptance.

### Next serial integration boundary

The current public `runtime-advance-until-gate` and `resume` paths still require
`TEST_ONLY_IDEMPOTENT_ADAPTERS`. The packaged Program Driver is also explicitly
a read-only pre-verification interface. Removing either guard alone is not a
production adapter implementation. The next integration must consume the native
plans above, bind verified executable invocations, retain Job leases, and route
actual process outcomes through the existing transition engine.

The generic engine owns its SQLite event stream, while the compatibility startup
providers currently commit a JSONL/state-file transaction. These must not become
two independently writable controllers for one Program. Integration needs one
authoritative event stream and reconstructible projections, plus command-attempt
recovery that cannot blindly replay a side effect after a crash. The existing
kernel crash tests assume idempotent adapters; they do not establish that an
arbitrary production process is idempotent.

The generic runtime currently also requires positive Architecture/Control Plane
epochs. The target's frozen values are null (portable compatibility sentinel
zero). Preserve that distinction: neither inventing a lock nor converting zero
to one can close this binding. Cover the chosen compatibility representation,
real process failure/reentry and the first project Workpack in an ordinary
temporary build-path test before requesting another formal Candidate epoch.

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
