# Execution startup repair and acceptance

Status: IN_PROGRESS. A bound Execution Root is not a running Harness.

Current engineering objective: Foundry execution startup and its regressions.
The user removed complete target Harness/media delivery from the active goal;
this does not edit the separate frozen target Requirement or grant execution.

Latest slice: the native Lab protocol verifier now calls the selected project's
implementation through the approved offline receiver and commits its actual
protocol observation. Coding prerequisites, immutable verification arguments,
read-only worker scope and a stop before Workpack acceptance are enforced.
Post-observation control results now have a separate producer and are excluded
from coding-command writes, while remaining mandatory Workpack outputs.
The first coding preflight now consumes actual committed startup capability
evidence, not just the expected startup order. Later Workpack capabilities remain
unresolved until their independent acceptance provider is implemented.
Startup/offline process integration and the first coding-stage transport have
temporary test evidence; real model transport and complete independent Workpack
acceptance remain unverified. See [protocol support](LAB_PROTOCOL_SUPPORT.md) and
[completion audit](WORKPACK_COMPLETION_AUDIT.md) for the boundaries. The sections
below retain earlier checkpoints in chronological order; their test counts
describe those individual source states.

## Cumulative implementation evidence

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

### Native startup under the existing SQLite controller

`startup_runtime.py` now connects the three Candidate-native startup actions to
the same `ControlEventStore` used by the approved local process adapter. The
public `advance-until-gate`, `checkpoint` and `resume` routes accept
`START_PACKAGE_SQLITE_REGISTRATION`. This route requires an existing approved
Parent and controller; it does not create either authority or an execution root.
The complete startup plan, actual roots, Factory locator and audited approval
projection are visible in the Parent challenge. Its three transitions come from
the published Candidate DAG and stop before `LAB_BOOTSTRAP`.

The native providers expose `prepare_action`, reusing their original semantic
input validation and payload construction without acquiring a second lease or
committing a native result, journal, event or state. The third action invokes
the actual fixed read-only Driver probes, not a Driver loop. Their environment
does not forward caller secrets or Python startup hooks. These trusted probe
processes are not the separately sandboxed Job receiver. The probe's whole-tree
mutation check requires full execution-root reads, which the startup plan now
discloses rather than claiming a narrower Job read scope.

The adapter projects each native one-shot authorization from the SQLite
Parent's actually reserved Grant. Candidate-decision provenance remains intact,
including a delegated actor; no machine grant becomes a fabricated human
approval. A native `PREPARED` proposal is durably observed before the kernel's
live binding recheck and authoritative commit. Result files, native state and
JSONL events are reconstructible views of committed SQLite records. The
Producer profile and independent Validator explicitly identify SQLite as the
journal and mark the old native transaction protocol as unexecuted by this
route. Static API inspection checks availability, not behavioral read-only
correctness; the latter has actual execution tests.

The legacy three startup writers and legacy hydrated Workpack runner reject a
SQLite-owned control root. Local process preparation accepts native views only
when this same SQLite stream owns all three startup results and their bytes
match. Existing unowned JSONL history is neither imported nor overwritten;
historical migration remains a separate, unimplemented operation. The portable
runtime inventory includes the adapter and tests its real import closure.

Temporary ordinary Candidates, generated through the actual Factory without
Compiler or Validator mocks, exercise native startup, checkpoint/resume,
observed-proposal recovery without repeat preparation, reconstruction of damaged
derived views, refusal of unowned legacy state and legacy writers, stale Factory
approval, missing Parent and skipped predecessors. An input-publication failure
is observed as failure and is not replayed. A separate real sandbox test then
executes a narrowed Job process under a new approved TEST ONLY Parent in the
same controller, producing its expected bytes. Its fourth committed transition
proves controller/receiver continuity, not Workpack acceptance or a skipped Lab.

The final actual startup/receiver/approval suite passed all 51 tests in 103.405
seconds on 2026-09-07, including the 15 opt-in real sandbox tests, using Codex CLI
0.153.3 and Python 3.14.5. Raw logs are retained locally under ignored
`build/startup-sqlite-runtime.VK98wO/`; they are not production execution
receipts. The first complete run found one old exact module-inventory assertion
that omitted the new startup module. Updating that expected inventory preserved
the completeness check; no Producer or Validator relaxation was used. The
corrected full suite ran 624 tests in 521.609 seconds: 609 passed and the 15
opt-in sandbox tests were skipped in the restricted runner. The final full log
is `unittest-final.log`; the earlier failure remains in `unittest.log`.
Official core validation passed 26 selectors covering 41 capabilities;
`verify-spec`, `validate_skill.py` and `git diff --check` passed. Read-only
inspection still reports the formal Program at revision 191 and
`PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`; its existing Execution Root has
only the original runtime binding file.

This closes the fresh-controller startup integration slice, not the full build.
Runtime initialization and Parent approval currently use the kernel API; an
operator-facing CLI bootstrap/approval path is not implemented by this slice.
Still open: that entrypoint, reconciliation when a process has no observed
outcome, model-service transport, native Workpack/artifact acceptance and the
complete ordinary build DAG. The immutable epoch 29 Candidate and its completed
authoring delegation remain unchanged; repaired output needs fresh authoring
authority. Lab, Linkage
and the target's three narrated animated videos have not been built by these
tests. A test Job exit code is not evidence for any of those deliverables.

### Public runtime authorization entrypoints

The public CLI now exposes `prepare-runtime-authorization`,
`approve-runtime-authorization` and `revoke-runtime-authorization`, documented in
[Local runtime authorization](LOCAL_RUNTIME_AUTHORIZATION.md). This closes the
operator-entrypoint gap noted in the previous slice without a second grant
database, fabricated human receipt or automatic command dispatch.

Readback checks the actual Factory/Candidate and shows the complete existing
Parent plan, including controller initialization effects. Approval validation is
factored from the existing kernel protocol into a pure receipt builder, so it
runs before root or database creation. Registration still writes the same native
Parent event. The public route checks Program ownership again inside that same
SQLite transaction. A native empty store can resume initialization; incompatible
or another Program's stores and unowned legacy control files are not adopted.

The existing kernel revoke operation now optionally retains the human actor and
reason. The public revocation path does not require a still-valid Factory
decision: cancellation remains possible after REOPEN or expiry. It prevents
future dispatch/commit, not OS-process termination or rollback of earlier
effects. Approval and revocation reentry do not grant a second budget or revive
a revoked Parent. No model transport or target-build approval is implied.

Actual temporary Candidate tests enter these public commands without calling
the internal registration API. They cover absent-root readback, initialization,
exact decision replay, native startup, another separately approved Parent and a
real sandbox Job output. Negative coverage checks changed scope, missing/human
identity, delegated actor substitution, bad decision time, stale Factory state,
path substitution, existing non-native database preservation, revocation and a
Program ownership change after preflight. That last failure test injects a real
competing stream after the real live verifier; it does not fake a success result.

The initial integration test identified a legitimate read-only macOS locator
alias (`/var` versus `/private/var`). Overlap checks now use its resolved physical
identity while preserving the approved locator spelling. Canonical, unlinked
write roots remain required. The 24-test focused authorization/kernel run passed
with one opt-in sandbox skip. The actual public-authorization/startup/approval
suite then passed all 33 tests in 215.645 seconds; the separate existing
receiver/adapter suite passed all 28 tests in 13.112 seconds. Together these runs
include all 16 opt-in sandbox tests. They used Codex CLI 0.153.3 and Python
3.14.5, with raw output under ignored `build/runtime-authorization.TuD4V6/`.
Official core validation passed its 26 selectors for 41 capabilities;
`verify-spec`, `validate_skill.py` and whitespace checks passed. The complete
suite ran 634 tests in 859.009 seconds: 618 passed and the 16 opt-in sandbox
tests were skipped in the restricted runner. Its raw output is retained in
`unittest.log` alongside the two actual sandbox logs.

The formal Program remains revision 191 at
`PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`. Its immutable epoch 29 Candidate
has not been regenerated, and no target runtime approval was submitted. The
remaining build work is lost-process reconciliation, model-service transport,
native Workpack/artifact acceptance, complete Lab/Linkage/Harness execution and
the three target videos. This entrypoint is a tested prerequisite, not evidence
that those deliverables exist.

### Coding input and result protocol

The first Lab Workpack is a native coding command, not an offline local
process. The new [coding protocol boundary](CODING_COMMAND_PROTOCOL.md)
provides Candidate-derived input planning through the packaged `coding-plan`
entrypoint and classifies the observed Codex JSONL lifecycle. It retains the
full selected task/capsule, native Job scope and declared ordering; it does not
activate any of them. The producer packages the helper and the independent
Validator requires that runtime module. A missing semantic task bundle is an
explicit unsupported input, not a generic prompt fallback.

The initial focused test incorrectly expected structural-only fixtures to
contain semantic task bundles. The corrected tests retain that case as a
negative and use the existing explicit-production Requirement fixture for
positive task-planning checks. Both Candidates are normally compiled without
mocking the Compiler/Validator or injecting startup execution contracts. This
did not require changing the Requirement semantics or weakening validation.
The first 25-test focused protocol/normal-Workpack suite passed in 7.112 seconds.
The complete regression then found a packaging regression introduced in this
slice: adding the coding helper to the common control bundle gave historical
control-only configurations a missing Workpack import. The failed full run was
stopped and its log retained. The producer now includes the helper only with
the Workpack provider, and its independent completeness check lives at that
same boundary. A missing-helper test and the historical control-only suites
cover the correction; this is not a Validator exemption.

After correction, the focused protocol, normal Workpack and historical
control-only/registration suite passed all 45 tests in 26.372 seconds. The final
complete suite passed 647 tests in 617.640 seconds (631 passed, 16 opt-in real
sandbox tests skipped). The unchanged sandbox receiver was not exercised live
again in this slice. Official core validation passed 26 selectors covering 41
capabilities; `verify-spec`, `validate_skill.py` and `git diff --check` passed.
Raw failed-run, focused and final-run output is retained in the ignored local
`build/coding-protocol.uMRiw2/` directory. The formal Program remained revision
191 at `PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`; its Candidate, Execution
Root, grant and frozen Requirement were not changed.

Installed Codex CLI 0.153.3 help and current official documentation were checked
without calling a model. Protocol tests include a real local Python process
that echoes TEST JSON; this is not Codex generation. A complete model turn is
classified separately from Workpack acceptance. Missing/truncated/malformed
captures and timeout cannot authorize a retry. The model dispatch adapter,
effective configuration/service authorization, durable model outcome capture
and independent native Workpack acceptance remain unimplemented. This slice
must not be reported as the full execution connector or a completed build.

### First coding-stage service adapter

The coding adapter now uses the existing public runtime authorization and
durable SQLite engine, not a second grant database or an agent-written receipt.
It retains the complete Candidate-native task and adds a resolved mapping of
only its approved read/write resources for stdin. Coding service/auth/client
effects are explicit in a separate Parent; no offline Parent or completed
pre-build grant is widened. Current authority is rechecked after local receiver
probes and immediately before dispatch. The public checkpoint/resume route
retains the same plan, and observed outcomes recover without another dispatch.

The native startup predecessor evidence is verified before the first Lab
coding task. Later Workpacks/commands remain blocked on independent acceptance;
a completed model turn produces no Workpack capability. The result contract
explicitly requires `workpack_accepted=false`. This is a first-command connector,
not a complete Lab/Linkage/Harness scheduler or acceptance provider.

Three integration issues were found and corrected in this slice. The new test
fixture initially retained another fixture's unregistered source ID; it now
uses the real authoring turn's source registration rather than bypassing the
Requirement checks. The adapter result needed the existing kernel's explicit
boolean/enum schema dialect. Finally, the portable task prompt needed an actual
host resource mapping; keeping logical paths alone was insufficient for model
input discovery. A regression now checks that the complete portable task is
unchanged and the mapping matches the effective scope, excluding Factory/auth
paths. The earlier full run was deliberately interrupted for this functional
correction, not reported as a completed regression.

The corrected focused process/Factory/startup/recovery/portable-Workpack suite
passed 32 tests in 85.795 seconds. The shared local capture receiver changed, so
the real offline Codex sandbox suite was rerun: all 28 tests passed in 10.150
seconds, including its 12 opt-in sandbox tests. Model transport tests use an
explicitly fake Codex executable and TEST events; no real model service request,
account/configuration change or formal target command occurred. Additional
system/project configuration remains unsupported until explicit hydration;
live model and selected-Job coding validation remain outstanding.

The final full suite ran 661 tests in 643.574 seconds: 645 passed and 16
opt-in sandbox tests were skipped by the restricted runner. The other four
startup/authorization/Factory-binding sandbox tests then passed separately in
25.745 seconds; together the two real offline runs cover all 16 skipped tests.
Official core validation, `verify-spec`, `validate_skill.py` and
`git diff --check` passed after the final source change. Raw failed, interrupted,
focused, final and actual offline results are retained under ignored local
`build/coding-runtime.Y2fbtl/`, not exported as generated target evidence.
The formal Program was checked read-only and remained revision 191 at
`PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`. No frozen Candidate, Requirement,
formal Execution Root or completed pre-build grant was changed or reused.

Next implementation dependency: consume the actual selected Workpack's artifact
obligations and independent validation/Oracle contract on the existing stream,
then permit its declared successor only from accepted evidence. Do not derive
that capability from the model message, JSONL completion, file existence or an
offline process exit alone. Until that provider exists, keep the explicit
predecessor stop instead of inserting a synthetic acceptance receipt.

## Workpack completion planning and observation checkpoint

The producer now packages `completion-plan` and `audit-completion` with their
runtime import closure; the independent Validator checks that closure. The
planner retains complete native Workpack/task contracts, not only their output
schemas. The audit observes matched committed command attempts and shared JSON
schemas. It explicitly leaves semantic validation and Oracles unevaluated,
does not read Job artifacts without a lease, and never grants a capability or
advances a successor. This is not the independent acceptance provider described
in the next implementation dependency above.

The first read-only audit test reproduced SQLite sidecar writes. The audit now
opens only a disposable copy of the database and its WAL, with source-change
detection, leaving the source controller and its auxiliary files untouched.
A test-fixture correction was also required: an open connection alone did not
retain the committed WAL; the test now holds an actual read transaction. This
diagnostic copy is not used as a transactionally locked backup or runtime
authorization source. See [the audit boundary](WORKPACK_COMPLETION_AUDIT.md).

Integration also reproduced an undeclared-dependency failure in `package-local`
and thus core validation. The portable producer now derives import declarations
and its optional-dependency manifest from the same route table, verifies the
matching installation extras, and diagnoses a missing manifest route. The new
dependencies remain optional: actual relocated `-S` startup passes, and an
audit without the extras reports unavailable Schema evidence. This fixes the
producer contract rather than simply bypassing the dependency scanner.

The corrected focused portable/Workpack suite passed 38 tests in 36.086 seconds.
An earlier targeted invocation failed to import an existing shared test helper;
the successful invocation includes the repository's `tests` path. The first
full run was stopped after the actual portable failure was identified and before
the source correction; it is not a completed regression. Failed/interrupted and
corrected logs are retained under ignored `build/workpack-completion.onL38N/`.

The final complete suite ran 674 tests in 665.735 seconds: 658 passed and the
16 opt-in offline sandbox tests were skipped by the restricted runner. Those
16 are not claimed as executed in this slice; their separately run evidence
belongs to the preceding checkpoint. Core validation (26 exact selectors),
`verify-spec`, `validate_skill.py` and `git diff --check` passed. No real model
request, target installation, media generation or formal Workpack ran.

Read-only formal handoff still rejects the epoch 29 Candidate under the repaired
current Validator: its old startup/runtime artifacts and command/read bindings
do not meet the current producer contract. Program revision 191 remains
`PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`, with only `REOPEN` allowed and no
active delegated intents. No formal Candidate, authoring state or Execution
Root was changed. Fresh authoring authority and an independent semantic
acceptance provider are still required; these tests do not close the target
Harness, Lab/Linkage or the three requested videos.

## Executable Lab protocol foundations and schema-loading checkpoint

Foundry now supplies portable pure protocol primitives for schema validation,
registry/operator/evidence lookup, immutable Job identity and schema binding.
The existing producer's schema binder was extracted into that library so the
future built Lab need not copy a subtly different algorithm or import the
Factory compiler. Independently authored behavior probes call the implementation
with valid and invalid inputs; they do not use its self-tests or stdout PASS as
their expected outcomes. All eight deliberately stubbed API variants fail.

The first real probe failed five public-request cases because the common schema
could not load: its `$id` contained a non-empty fragment. Producer and independent
Validator now use a valid canonical identifier, with a regression that rejects
the old form and loads the corrected schema using the actual 2020-12 metaschema.
Normal Candidate tests additionally load every emitted standalone validation
schema. This is a reproduced runtime-compatibility defect, not a hypothetical
adversarial scenario or a reason to weaken schema validation.

Lab completion scope now identifies current implementation obligations by exact
reference and owner. The complete shared interfaces, CLI IDs and registry
contracts remain present, but do not require later Workpacks to have completed
before the current one. The independent scope check rejects a wrong owner,
missing obligation, or moving implementation obligations into shared context.
The existing artifact and prerequisite contracts are not removed.

The corrected focused protocol/normal-Workpack/portable suite passed 38 tests in
27.999 seconds. Its 11 protocol tests include actual packaged execution of the
28 behavior probes, bad-implementation variants, schema loading and phase-scope
regressions. Raw initial failure, focused and final results are retained under
ignored `build/lab-protocol.K9fud1/`. Core validation, `verify-spec` and skill
validation passed. Program revision 191 was checked read-only and remains
`PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`; no completed grant was reused.

The first full run then exposed an introduced dependency-routing regression:
51 tests failed with the same two dangling support-module references. Semantic
compatibility Candidates referenced the new protocol support but did not use the
local Workpack profile that initially emitted it. The producer now materializes
the two pure modules whenever the semantic bundle declares the dependency,
without enabling a Workpack runtime or creating an Execution Root. The new
compatibility regression verifies that only the support package is introduced.
After correction, 39 focused tests passed in 32.118 seconds and the complete
66-test semantic-production suite passed in 132.019 seconds. This repair changes
the producer dependency route; the dangling-reference Validator remains intact.

The corrected complete suite ran 686 tests in 942.770 seconds: 670 passed, with
16 opt-in offline sandbox tests skipped by this restricted runner. Those 16
were not executed in this slice. Final core validation (26 exact selectors),
`verify-spec`, `validate_skill.py` and `git diff --check` passed. The original
failed full run and corrected full log remain separate in the diagnostic
directory above; the passing result does not erase the introduced regression.
These are source and temporary packaged-library checks, not a real model turn,
formal Workpack run or independent Workpack acceptance.

Remaining Foundry integration: bind an independent verification command to the
selected project's implementation, run it under the approved isolated local
receiver, verify the complete owned scope and prerequisite provenance, and
commit genuine Workpack acceptance before allowing its successor. The new
protocol support does not dispatch that worker, implement every domain-specific
Lab/target algorithm, or claim Workpack acceptance. A real model transport check
also remains separate from TEST-only subprocess evidence. Completing the target
video products is no longer the active Foundry engineering goal's endpoint.

## Native project verification command and runtime integration

`LAB-PROTOCOL` previously declared only its coding command, while independent
verification was prose. The producer now adds `LAB-PROTOCOL-CHECK` after coding,
materializes its worker by the declared Lab dependency on every relevant route,
and projects a read-only command with no artifact-write roots. The independent
Validator checks the worker/project/schema recipe, role, order and write scope.
The native Task Bundle identifies the project's `external_lab.protocol` API.

The public packaged `verification-plan` is read-only. The existing offline
runtime binds its interpreter resource under the approved Parent, compares the
fresh native recipe and requires the actual committed coding observation before
dispatch. It imports no project code in the controller. The worker calls all
28 independent behavior probes, capturing its structured report in the existing
process result and SQLite observation/commit flow. Missing code, a broken schema
implementation, incomplete output and worker substitution are not successful
verification. A protocol PASS still grants no Workpack capability or successor.

Integration also reproduced an inherited-continuation gap: the generic local
hydrator retained an input transition's successor/retry policy for the new
verification command. The producer-side hydrator now removes both and Parent
validation rejects reintroduction. This fixes execution flow, not just validation
labels. The earlier full regression was interrupted for this actual source
change; it is not counted as a completed passing run.

The initial 6-test integration suite passed in 32.769 seconds. The broader
runtime/acceptance suite passed 35 tests in 183.320 seconds, including failed
behavior and recovery without redispatch. The producer suite's 96 tests found
one test-fixture path error: the new worker lives directly under `tools/`, not
inside the runtime package. The fixture now uses that actual path; no missing-file
check was removed. A focused invocation also needed the existing `tests` import
path for a legacy shared test helper.

Actual offline OS-sandbox verification passed in 2.684 seconds: correct project
behavior runs and a project implementation's attempt to rewrite itself raises
`PermissionError`, with the temporary tree unchanged. The first restricted
attempt could not apply a nested sandbox and dispatched no worker. An outer
runner approval preserved the inner sandbox; the subsequent venv startup failure
was resolved by explicitly binding the verified host Python installation and
loader/link metadata reads. The production receiver did not widen permissions,
change argv to a different Python or fall back to unsandboxed execution.

The next full run reproduced a minimal-startup packaging regression:
`local_runtime.py` directly imported the newly optional Workpack verification
component, which that small bundle does not provide. The shared receiver now
loads it only for a native independent-verification command, following the
existing optional coding-component pattern. Full Workpack bundles still ship
and require the component; minimal bundles report provider unavailable if that
unsupported route is selected. The original portable self-check stays intact.
Its regression also executes an actual import and ordinary-command provider
selection from the relocated minimal package. The corrected closure suite ran
17 tests in 65.495 seconds, with 16 passed and one opt-in OS test skipped.
The 28-test normal-project focused run passed 27 with one skip. Both interrupted
full runs at that point were retained separately, not counted as successful
complete regressions.

Historical release-closure coverage then exposed a separate composition defect:
the Epoch 1/2 producer hashed every Python module in the shared runtime directory
into its control-plane manifest. Adding unrelated Lab support therefore changed
the claimed control-plane implementation set. Both producers now derive that
manifest from the exact module list they own. Epoch 2's independent and standalone
Validators retain their original exact-set checks. Epoch 1's standalone checker
had the same directory-scan coupling and its Factory checker lacked exact-set
validation; both now independently require the declared control module set.
Whole-package inventory still covers the Lab files. Regression assertions verify
this separation on both
control-plane generations. The Epoch 38 fixture's module-set and byte-copy
expectations now include the genuinely declared Lab dependency. The two concrete
failure reproductions passed after correction; the interrupted full run and the
fresh complete/legacy-suite runs remain separately logged. The broader 86-test
legacy run confirmed the Epoch 2 repair but exposed three Epoch 1 standalone
failures; those are retained, not reported as a pass. A new regression rejects
both omitted control modules and unrelated Lab-module records even when their
file digests and surrounding inventory are internally consistent.

The corrected complete legacy group passed 87 tests in 150.546 seconds. Latest
core validation, `verify-spec`, `validate_skill.py` and `git diff --check` passed.
The final integrated full regression completed in 755.144 seconds: 697 tests,
680 passed and 17 explicitly opt-in tests skipped (`unittest-final-integrated.log`).
The separate actual offline sandbox result above is additional evidence, not a
claim that the 17 skipped tests ran. This verified source checkpoint is saved
locally; no remote publication is included.

Logs remain under ignored `build/project-verification.PpLizI/`. Formal Program
revision 191 remains `PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`, with only
`REOPEN` available and no active delegated intents. No formal Candidate mutation,
model turn, Workpack execution, installation, lifecycle advance or GitHub push
occurred. Full owned-scope acceptance and successor integration remain open.

## Structural receipt producer ownership

After local checkpoint `12a0c98`, a normal produced Candidate regression proved
that a coding command's effective write roots included its own future
`WORKPACK_CONTROL_RESULT`. The artifact required completed command evidence and
an independent Oracle, so assigning it to the preceding task created a circular
production dependency (`ownership-before-write-domain.log`).

The producer now labels these artifacts as acceptance-controller outputs after
native commands and Oracles. Complete required artifact sets and overall
Workpack/DAG domains stay unchanged. Both initial command materialization and
semantic binding refresh exclude the controller roots from command writes.
Factory and portable Validators independently check role/timing and the split
write projection. The completion planner exposes the two producer groups and
the coding prompt distinguishes task scope from the broader Workpack context.
No new hashing or authorization layer is added.

Five focused regressions passed in 2.510 seconds. The first wider integration
run found a disposable-copy test permission error, not a product failure:
`copytree` retained Candidate read-only file modes. The mutation test now makes
only its two copied fixture files writable, retains the original Candidate,
refreshes the directly affected binding and proves the specific semantic failure
in both Oracles. That earlier 33-test run remains recorded as failed, not PASS.
Updated core validation, `verify-spec`, `validate_skill.py` and `git diff --check`
passed. The ownership slice's complete regression finished in 876.029 seconds:
702 tests, 685 passed and 17 opt-in tests skipped
(`build/project-verification.PpLizI/ownership-full.log`). This checkpoint is
saved locally. The subsequently developed, as-yet unintegrated capability reader
is not included in that 702-test result.

Workpack acceptance, current implementation-byte evidence, capability provenance
and successor integration still need implementation. Correct writer ownership
does not publish a receipt or discharge those requirements. No formal Program,
Candidate, execution grant, model service or GitHub state was changed.

## Startup capability provenance and native observation reuse

Local checkpoint `f5f3cc8` closes structural receipt ownership. The next normal
startup fixture reproduced an execution-preflight gap: changing a task's required
capability to one absent from the startup result was not rejected by
`_predecessors`, which only checked startup order and the selected node
(`capability-preflight-before.log`).
This is a component-level missing evidence-consumption check, not proof of an
end-to-end authorization bypass: fresh Candidate/task and Parent validation
already reject a caller's rewritten task. The shared provenance reader provides
the actual capability evidence needed by the subsequent acceptance controller.

`workpack_evidence.py` now selects real observed-and-committed native attempts
from the same approved Parent, Program, Candidate and attempt. The capability
reader follows each required capability's declared startup node and checks the
actual native result. Coding preflight consumes it; the read-only audit reports
the same evidence. Command observation selection reuses this implementation
while retaining exact project/task/command bindings and real process/model-turn
completion checks. Producer packaging and independent closure validation include
the new module; minimal startup bundles remain unchanged.

Eight focused tests passed in 11.059 seconds using actual temporary Factory,
startup and SQLite execution but no coding/model process. They cover provenance,
missing observation/commit, another Program/Candidate/attempt, unsupported
Workpack sources, missing capability, the consumer preflight and read-only audit.
The broader coding/verification/acceptance integration suite completed in 209.401
seconds: 53 tests, 52 passed and one opt-in sandbox test skipped. It includes the
first seven new tests; the eighth audit test also passed in the separate focused
run above. Core validation, `verify-spec`, `validate_skill.py` and
`git diff --check` passed. The complete capability slice then passed 710 tests
in 820.051 seconds: 693 passed and 17 opt-in tests skipped (`capability-full.log`).
This source checkpoint is saved locally. The subsequently developed frozen-
declaration checker is not included in that result.

This is not full Workpack acceptance. The missing independent owned-scope Oracle,
current implementation-byte evidence, Workpack-produced capability provider,
acceptance receipt publication and successor integration remain explicit. No
formal Candidate mutation, additional runtime authority, model call or GitHub
push occurred. Logs are under `build/project-verification.PpLizI/capability-*`.

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
