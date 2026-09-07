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

### Serial integration baseline (before the slices below)

The public `advance-until-gate` and `resume` paths at this baseline required
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

### Durable command delivery prerequisite

The generic kernel now accepts the explicit command-contract mode
`DURABLE_SINGLE_ATTEMPT`. Before invoking that command, it atomically reserves
the attempt in the existing SQLite control event stream. After validating the
returned result against its declared schema, it records `COMMAND_RESULT_OBSERVED`
before finalizing the transition. There is no second result database or new
authorization class. The store's `require_new` reservation option prevents an
idempotent insert replay from becoming a second caller's permission to execute.
Input identity reuses the existing Decision Receipt digest in the same atomic
intent batch; it does not add a duplicate command-input digest field.

Reentry finalizes an already observed result without calling an adapter or
issuing another grant. An intent without a recorded result returns the read-only
`COMMAND_OUTCOME_PENDING` / `COMMAND_OUTCOME_UNRESOLVED` state; it cannot silently
rerun the same command or advance another node. It does not write a stop event
over the active caller's event tip, assume that process has terminated, or add a
Human Gate merely because the outcome is not yet observed. A production adapter
must inspect its actual process handle, wait if still live, and reconcile a
proven lost outcome before attempting any new side effect. Deterministic failure remains terminal
within the same Parent, while a declared pre-effect temporary failure retains
the existing bounded retry policy. Reentry can still return an earlier completed
node while a successor is pending. Contract/input changes and revoked authority
do not cause a pending command to be redispatched.

The new test module uses independent kernel client processes and a genuinely
non-idempotent local child process. It covers process death before observation,
death after observation, real exit-code failure, competing atomic reservations,
declared retry and public Runtime-advance recovery with no adapter available.
This is execution-delivery evidence, not production adapter, sandbox, Codex,
Lab/Linkage or target Harness evidence. It does not claim general exactly-once
external effects: a process whose outcome was not observed still needs explicit
reconciliation. The old implicit-idempotent fixture route is unchanged; it must
not be selected for production processes. The public CLI's test-adapter guard
remains in place until production scope enforcement and routing are implemented.

The existing Workpack runner labels resolved commands `network=DENY`, but its
`_run_command` only supplies a small environment to `subprocess.run`. That code
alone is not evidence of receiver-side network or filesystem enforcement,
especially for the Python postflight process. A production connector must bind
the receiver's actual enforcement capabilities (or stop when they are absent),
not infer them from environment filtering, CLI token presence or extra hashes.

The final durable-delivery slice adds 14 tests and passed the 41-test focused
control/recovery run in 7.886 seconds, followed by the complete 568-test suite
in 475.901 seconds (2026-09-07). `verify-spec`, `validate_skill.py` and
`git diff --check` passed. The formal Program remains at revision 191; the
published Candidate still has its original 297 files and content binding, and
the Execution Root still contains only its runtime binding file. These results
close this delivery prerequisite, not the remaining production build chain.

### Local offline process receiver

`local_process.py` now supplies a finite-command receiver using the installed
Codex CLI's permission-profile sandbox. It is not an authorizer, a model client,
or an implicit replacement for the public CLI's test-only adapter route. Its
caller must first bind the Job's approved read/write leases to the actual local
resources. The receiver retains the original executable invocation (including
venv selection), applies a fresh inline profile with the documented `:minimal`
runtime baseline plus those explicit roots, and disables command networking.
It neither creates a global profile file nor silently adds writable temp roots.
Codex's own host-side startup/configuration is separate from workload scope.

The installed CLI uses flat `codex sandbox` syntax, not the old platform
subcommand examples. The receiver verifies that interface and probes the same
policy before workload dispatch. An unavailable interface, managed-policy
rejection or nested-sandbox failure cannot fall back to unrestricted execution.
Capability-probe output has its own bound so a small workload-output limit does
not hide required CLI options. Real exit codes, bounded output excerpts and
timeout state remain separate from artifact acceptance. Capture spills to
temporary files, bounding retained memory but **not** providing a disk quota.
POSIX process groups are cleaned up on exit/timeout; intentionally detached
daemons/new sessions are outside this finite-command route's supported workload.
A timeout with possible partial effects is not a retryable pre-effect failure.

The implementation reuses [Codex's documented permission profiles](https://learn.chatgpt.com/docs/permissions)
instead of maintaining custom SBPL. [Apple DTS's explanation](https://developer.apple.com/forums/thread/661939)
notes that custom SBPL is not a supported third-party API. These are dependency
choices, not a claim that Foundry has independently certified the host sandbox.
The observed host is macOS with Codex CLI 0.153.0; other hosts still need their
own real receiver tests. This receiver does not run `codex exec` or make model
requests. Model-service transport must remain distinct from the offline tools'
network policy in the later build connector.

`tests/test_local_process.py` separates ordinary contract/failure tests from an
opt-in real sandbox suite. The latter uses temporary inputs and output roots,
not a published Candidate or the target Execution Root. Run it with
`HFFACTORY_TEST_CODEX_SANDBOX` bound to the installed CLI and, when needed,
`HFFACTORY_TEST_PYTHON_READ_ROOTS` containing a JSON array of explicit host-local
interpreter dependency paths. Neither binding is portable project authority.
The tested Homebrew venv needed both its loader/link metadata tree and the
corresponding Python installation tree; a canonical Python executable worked
with narrower reads, but substituting it changed venv identity. The receiver
therefore preserves argv and requires the caller's complete dependency binding;
it does not guess broader installation roots after a failure.

Real tests cover input reads, output writes, unchanged venv identity, rejected
input/sibling/metadata writes and sibling reads, rejected local socket binding,
nonzero exit despite printed `PASS`, bounded output, timeout/normal-exit process
group cleanup and durable-kernel recovery without repeating a real side effect.
That recovery test stores the actual receiver result, including exit code and
output, in the existing SQLite command-result observation. A finite foreground
command PASS is still not a project test, Oracle or Workpack PASS.

Remaining serial integration: bind normal Workpack commands and transitive Job
read leases through one authoritative runtime controller; reconcile pending
process outcomes; preserve the target's null Architecture/Control epochs; expose
the production CLI only after those bindings and an ordinary full build-path
fixture are covered. The existing `workpack_runtime._run_command` is not yet
replaced by this receiver, and the public test-adapter guard remains. No formal
Candidate, Parent authority, execution state or completed delegation is changed
by this receiver implementation or its temporary tests.

Verification (2026-09-07): the explicit local receiver run passed all 15 tests
(7 contract tests and 8 real sandbox tests) in 6.191 seconds. The complete suite
then ran 583 tests in 479.853 seconds: 575 passed and those 8 opt-in real sandbox
tests were skipped in the ordinary restricted runner, not relabelled PASS.
`verify-spec`, `validate_skill.py` and the whitespace checks passed. The formal
Program remained revision 191, and its Execution Root still contained only
the original runtime binding file. No models or formal Workpacks were run.

### Approved local process-stage adapter

`local_runtime.py` connects the offline receiver to the existing durable SQLite
controller. This is a **process-stage interface**, not a normal Workpack or
Harness completion provider. It neither bootstraps authority nor migrates the
compatibility JSONL controller. An existing, explicitly approved Parent must
contain its complete `local_execution` plan: actual Candidate/input root,
execution root, controller database, receiver executable binding, runtime-tool
resource mappings and full transitions. The readable Parent challenge includes
these fields and its read/write scope. A dispatch request can select unchanged
transitions from that plan, not replace their arguments or Job selection.

`bind_local_workpack_transition` retains the native command/lease contract and
binds exactly one declared Job where required. It combines shared reads, the
selected Job's reads/writes, explicitly mapped runtime dependencies, and read-only
access to that Job's lease receipt. The resulting grant must remain within the
Parent. Workloads cannot write the Candidate, runtime tools or controller;
runtime-tool aliases cannot reopen another Job or controller domain. Model/code
generation and Driver commands are rejected by this offline transport.

Before dispatch, the adapter rechecks the live approved Parent, reserved Grant,
actual wall-clock expiry and executable bytes. The native lease JSON is an
atomic projection of this persisted attempt, with the existing scope fields,
Grant identity and fencing token. It passes the Producer's native receipt
schema, without a second authorization ledger. Its `ACTIVE`/`consumed=false`
fields describe **issuance**, not continuing bearer authority: current consume
and revocation state lives in SQLite. The workload can read but not write its
receipt. Controller projection and workload effects are distinguished.

The public `advance-until-gate` and `resume` commands accept the explicit
`adapter_mode=LOCAL_OFFLINE_PROCESSES`; the old test-only mode remains guarded.
Local requests cannot supply `test_adapter_results` or `created_at`. They use
the existing expected bindings/state and budget fields. Missing databases do
not create an execution root; existing compatibility controller files cause a
typed migration stop rather than dual writes. Unknown receiver outcomes remain
unknown effects; observed outcomes recover without redispatch. Path completion
retains the kernel's `STOPPED_AT_REAL_GATE` / `TRANSITION_PATH_COMPLETE` response,
not a claim of target acceptance. Successful resume returns `RESUMED` with the
individual committed transition receipt.

The integration also reproduced a Producer read-scope gap: a normal final
`LAB-SELFTEST` command had an empty read list despite its repository cwd. Adding
reads only to initial materialization was insufficient: portable command
reconstruction and semantic hydration removed them again. All three production
paths now retain Candidate/repository reads, and the independent Validator
derives those required reads itself. Tests inspect the final ordinary Candidate,
not only the initial helper; they also remove/re-hash a command's reads and
verify semantic rejection after updating the relevant inventory binding. The
portable runtime includes both new modules and tests their actual import closure.

The opt-in local adapter suite passed all 13 tests in 4.478 seconds (2026-09-07),
including four real public CLI/sandbox tests without test adapters. They observe
actual output bytes, read the native lease inside the sandbox, validate its
schema, verify one consumed narrowed Grant, reject printed `PASS` with exit 7,
recover a non-idempotent effect once, and exercise public capsule resume. The
other nine tests cover plan/Job replacement, missing authority/store, old
controller files, fake results/time, model/Driver routing, lease ownership,
physical tool aliasing, executable drift and real-clock expiry. These are
temporary local process fixtures, not model, Lab, Linkage or media evidence.

Still open for the normal full build: audited Candidate-decision/build-grant
integration at dispatch, the target's null Architecture/Control epoch binding,
one-controller migration/startup, pending-process reconciliation when no outcome
was observed, model transport, and Workpack/DAG acceptance. This local receiver
does not verify a native command's entire artifact acceptance contract merely
because the process exits zero. It does not replace the legacy Workpack runner
or make the immutable epoch 29 Candidate executable under the repaired source.

Final verification (2026-09-07): the complete suite ran 599 tests in 546.421
seconds, with 587 passing and the 12 opt-in sandbox tests skipped in the
restricted runner. A separate receiver/adapter run passed all 28 tests in
10.840 seconds, including those 12 real sandbox tests, on Codex CLI 0.153.3 and
Python 3.14.5 (jsonschema 4.26.0, cryptography 48.0.0). Two older tests' exact
runtime-module inventories were updated for the newly packaged modules; the
final full run includes both corrected checks. `verify-spec`, `validate_skill`
and whitespace validation passed. Raw run output is retained in ignored local
build artifacts, not a published Candidate or a production execution receipt.
The formal Program still reports revision 191 and
`PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`.

### Approved Start Package binding and recovery entrypoints

The local runtime now distinguishes `FACTORY_APPROVED_START_PACKAGE` from the
core dual-lock tuple. Its binding retains the actual Requirement Architecture
and Control Plane epochs: a null pair remains null; a matching positive pair
remains positive. The legacy dual-lock contract still rejects nulls. Portable
zero sentinels and the execution controller's counter are not Architecture locks.
No Requirement, Candidate, or approval digest is renamed to a fabricated lock
digest. The new shape reuses the existing Requirement digest, two distinct
Candidate identity domains, Factory state identity, and decision event reference.

`prepare-execution-handoff` returns that binding without authoring or runtime
writes. A separate runtime Parent must disclose the physical Candidate root,
read-only Factory database/runs locator, local process plan, Job scopes and
budgets in its readable approval challenge. This projection is not a Parent
grant, and the delegated pre-build actor is not relabelled as a human.

The public local `advance-until-gate`, `checkpoint` and `resume` paths read the
current Factory event/decision chain and published Candidate before reserving a
command or recording new recovery events. The kernel takes an injected host
verifier rather than importing the Factory service into its portable runtime.
The Start Package binding cannot dispatch without that verifier. A second live
check after durable result observation prevents a changed approval from being
committed as a current transition; the observation is retained and reentry does
not replay the effect. Returning an already recorded historical result is not
new execution authority. This is a local freshness check, not an atomic
transaction spanning Factory state, the process effect and the runtime database.

Production checkpoint requests use the same real-clock local mode as startup
and resume. They select a resume node from the persisted Parent plan, not a
caller-provided command. Caller timestamps and test-result payloads remain
invalid in this mode. Recovery still obeys the existing Parent, environment,
artifact, event-tip and fencing checks; unknown process outcomes are not turned
into successful results or automatic retries.

The new integration fixtures generate and approve an actual temporary ordinary
Candidate with null epochs, without mocking compilation, validation or the live
handoff. They cover unchanged byte domains, absent runtime authority, typed
epoch/Program mismatches, missing verifier, REOPEN and published byte drift,
wrong physical root, approval invalidation after an observed effect, and public
checkpoint/recovery rejection before new events. Two opt-in tests execute real
local Python through the public CLI and sandbox: direct startup, and checkpoint
followed by resume. All fixture approvals are explicitly TEST ONLY; these tests
do not approve or execute the target Program.

This closes the null-epoch and live Candidate-decision binding slice for scoped
local processes, not the whole build. One-controller startup/migration, a lost
process outcome with no observation, model transport, native Workpack acceptance
and the complete ordinary build DAG remain open. The existing epoch 29 Candidate
is unchanged and still requires fresh authoring authority and regeneration.

Verification (2026-09-07): the full suite ran 613 tests in 528.003 seconds,
with 599 passing and 14 opt-in sandbox tests skipped. The separate actual
receiver/adapter/approval run passed all 42 tests in 53.003 seconds, including
those 14 sandbox tests, on Codex CLI 0.153.3 and Python 3.14.5. The focused
kernel/CLI/handoff run passed 48 tests with 6 opt-in skips. Official core
validation passed its 26 selectors covering 41 capabilities; `verify-spec`,
`validate_skill.py` and whitespace checks passed. Raw verification output is
retained under ignored `build/approved-start-package-runtime.fXODxd/`.
The formal Program is still revision 191 with no execution authority, and its
existing Execution Root still contains only the runtime binding file.

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
