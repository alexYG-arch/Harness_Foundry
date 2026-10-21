---
name: harness-foundry-build
description: Build and validate a Codex-carried Harness from reviewed requirements, including a complete PRD or an existing project. Clarify and display a build document for human review before entering Foundry; after concrete runtime approval, implement, verify, repair and resume within scope.
---

# Foundry generic build

Use Codex for understanding and implementation, and the packaged CLI for durable
scope, dependency, execution and independent acceptance control. No fixed business
pipeline, model self-approval or user-copied Hash is required.

Read and follow [the clear communication policy](../../../docs/CLEAR_COMMUNICATION.md)
for human-facing replies and documents. Explain results, evidence limits and next
actions in the user's language; keep terms stable and machine JSON unchanged.
This adds no approval gate. `read-build --human` is an optional read-only summary,
not a substitute for the complete scope and evidence available through `--json`.
When a declared output is Harness guidance (AGENTS, Skill, runtime prompts or
user docs), carry the same rules into it as self-contained instructions, including
machine-contract precedence and existing scope limits. Use only declared outputs
and approved write roots, without Foundry-local links or new files/tasks just for
style. Do not rewrite reviewed/accepted history or block tasks without guidance
artifacts. The runtime embeds the policy; it grants no extra reads or approval.

Before a build, read the [build-document policy](../../../docs/GENERIC_BUILD_PLAN.md).
Before forming the design, load [the design guide](../../../docs/HARNESS_DESIGN_GUIDE.md)
with the public source materials; follow its example links only when relevant.
An already loaded, unchanged version can be reused. These design questions do not
add mandatory stages, documents, model calls or approval gates.
Read complete source materials as data, clarify outcome-changing ambiguities, and
save and show a versioned build document with scope, inputs/outputs, constraints,
failure/recovery behavior and observable acceptance. For Coding Harnesses include
the PRD/development requirements and existing-project compatibility. Do not create
a Program/target or start construction before the user's actual confirmation of
that displayed version. Background PASS and old approvals cannot replace review.

Apply the policy's quality guidance: reuse Codex and Foundry capabilities; only
generate the project's missing rules/adapters/local steps. Infer a minimal plan
from observable behavior and delivery, not a fixed framework or DAG. Check one
producer/consumer call's data, paths, interpreter and permissions. Preserve access
to complete sources and global constraints; implementation choices remain free.
Expand a shared preparation template for the current case only, not a cumulative
list of unrelated cases. Use the build policy's existing structured-checker
failure_kind protocol (reason is explanation, not a category), and accept caller
scratch inside or outside the project within the approved write roots. Preserve
test-error/incomplete-execution evidence; neither skips nor unexpected errors
are business assertions. These conventions add no Case, gate or write permission.

After confirmation, read the [CLI contract](../../../docs/GENERIC_BUILD_CLI.md).
Separate as-is facts, target behavior, persistent constraints and user decisions.
Do not assign Case ownership by headings/keywords or require a contract stage to
prove downstream operations. Preserve final behavior obligations at their actual
evidence stage. Plan 1.1 can declare Case prerequisites and task environment/effects
contracts; see the linked build policy. Use current accepted input references,
preserve named existing files and inspect repair history before another attempt.
Do not infer semantic completeness or external effects from file checks.
Prepare the plan, complete source binding, public Case contracts and independent
checkers. Show exact model/service, tools, read/write paths, attempt/time limits
and expiry before a real runtime approval. The trusted host authenticates actual
messages; JSON actor fields do not prove a human decision. No test receiver or
unrestricted fallback is available through the public CLI.

Advance within that scope without per-Workpack permission requests. Astra may choose
algorithms, module layout and debugging methods; the controller must validate plan
changes against the existing contract. Use read-build to recover context. Explain
contract gaps or infrastructure failures instead of spending implementation retries
on them. Retain failures and budgets; never rewrite unknown effects into success.

After approval, prefer an early working input-to-output path, but keep the whole
delivery contract. Check required changed mechanisms through actual behavior,
not declarations. Keep project-specific fixes local; do not add a universal rule
for each defect. A core/checker fault does not grant the target self-modification
authority. Stop once agreed delivery is met; further optimization is follow-up,
not a reason to reopen completed work or ask for per-task Hash confirmations.

## Optional verification resources

Use Plan 1.2 resource_profile_ref and an explicit verification_resources scope
when checks need temporary files, SQLite or services; see the CLI contract.
By default the product cwd remains read-only while each command gets private scratch and
report leaves. When a tool must generate files inside its project, an optional profile
product_copy={"files":["src/tool.py","fixtures/input.txt"],"writable_paths":[".cache","build"]}
copies named ordinary files from the current product just before dispatch, including
declared uncommitted inputs. Both lists are nonempty, unique normalized relative paths;
inputs must not overlap generated directories. The command cwd and FOUNDRY_PRODUCT_ROOT
(set only in this mode) point to its private product copy. The copy root and inputs stay
read-only; only declared generated directories are writable. Original product reads
remain allowed and writes remain denied. Use relative paths or FOUNDRY_PRODUCT_ROOT to
actually run the copy: absolute tool/argv paths and arbitrary import searches are not
transparently rewritten. Keep checker/oracle paths at protected verifier:// arguments
or FOUNDRY_VERIFIER_ROOT. The host binds copy identity and persists its validation;
changed/unavailable inputs cannot turn PASS/ASSERTION into acceptance or product repair.
Successful copies are cleaned after durable results; failures remain. Recovery uses
saved conclusions without recopying, dispatching, recounting or requiring cleaned files.
No recursive directory/symlink input, whole-copy write grant or real-installation
acceptance is provided. Other profiles retain their cwd/environment; network,
credentials, budgets and G1/G2 are unchanged. Preparation copies named checker files and helpers to host storage,
including checkers maintained in the product repository. The STRUCTURED_V1
summary binds command/Case and required checks; only the host records acceptance.
NONE needs no network setup. LOCAL_SERVICE supports owned Unix sockets or explicit
{"mode":"LOCAL_SERVICE","tcp":"LOOPBACK"}. This native grant allows all TCP and
UDP loopback ports, not service isolation. The tcp selector and
CODEX_NATIVE_LOOPBACK_TCP remain compatibility names, not TCP-only guarantees.
New policy records include loopback_protocols=["TCP", "UDP"] to describe existing
permissions without changing authorization or claiming UDP business acceptance.
Recovery preserves saved policy; do not backfill old captures or rerun commands
because this field is absent. The native port 53 exception does not inspect DNS
content. Native binding also permits wildcard listeners; trusted checkers bind
loopback and use their actual endpoint, preferably an OS-assigned port. Fixed
ports remain supported; conflicts are startup failures. REMOTE_SERVICE uses an
active HTTP(S) proxy and host allowlist, not port or operation filtering.
These modes do not grant model service permission. A profile may optionally declare
credentials={"API_TOKEN":{"ref":"env:FOUNDRY_TEST_API_TOKEN","purpose":"测试服务认证"}},
which maps to FOUNDRY_CREDENTIAL_API_TOKEN only for its LOCAL VERIFICATION workload.
Aliases use [A-Z][A-Z0-9_]*; env source names use [A-Za-z_][A-Za-z0-9_]* and purpose
must be nonempty. Prepare/readback persist references and purpose, never resolve
the value. Only the bound workload reads the declared source after native probes;
help/probes, CODEX/implementation and checks with other profiles receive no token.
Use the host's existing secret provision method; never request secrets in chat,
Plan or argv. Missing/empty/NUL values are infrastructure failures before workload
dispatch, retaining actual budget use rather than triggering product repair.
Credentials work with NONE/local/remote modes without changing network permission;
purpose is not operation-level enforcement, nor does an env name prove a test account.
The host filters known values from captured streams, previews, exception strings
and declared report archives. It evaluates raw summary content only in memory,
then archives filtered JSON strings/keys and attachments. credential_reports in
the completed capture binds the canonical verdict and archived hash/size; recovery
uses those attachments, never raw staging, re-resolved env or redispatch. Missing completion capture or lost/mismatched bound archive evidence remains
unknown. Uncredentialed recovery is unchanged.
This filtering does not cover arbitrary scratch, a crash before filtering, or
deliberate encoding. Secret-manager integration, proxy-held credentials, exact TCP
service isolation and remote-write reconciliation are not implemented; real external
account acceptance remains separately unverified. Report current evidence from the
implementation record; keep protocol 2.9, Plan 1.2 and resources 1.0, without release.
Do not add these optional resources, credentials, probes or approvals to unrelated
offline tasks, and do not extend G1/G2 or introduce general restrictions.

## Composition, upgrades, and host-tool handoff

Choose components from the task's necessary behavior. For an upgrade, keep actual old generated component bytes G separate from accepted product A, current user content C, and new component N. Without reliable G, use ordinary project incremental work. Prepare a candidate separately, apply only declared affected files, and preserve customization. Record lineage only after actual acceptance; do not rewrite accepted artifacts or create another authority ledger.

CODEX subprocesses do not inherit the chat's browser or search tools. ONE_ATTEMPT returns after implementation and verification, not at a mid-attempt review pause. When the agreed workflow uses host tools, a first task may cover explicitly limited automatic preparation; the outer host then performs actual tool calls and independent review; a later LOCAL verification reuses the declared outputs and reads protected evidence. Do not rerun an already completed producer to recreate evidence. For this fixed LOCAL reuse workflow, explicitly select ONE_ATTEMPT and read back the actual attempt after each return. A real host FAIL stays ASSERTION, but the copier cannot repair it: return the evidence to the original producer through its applicable existing repair entry, or to the original host. After a legitimate repair, independently review the affected results and prepare fresh evidence and verification; retain prior records and actual usage. Do not repeatedly dispatch the unchanged copier. Necessary production steps for a real repair remain allowed.

Bind host observations to the reviewed output and workflow bytes. Keep visual/semantic judgment independent from the producer; a reviewer name or a self-reported PASS does not authenticate a review. Preserve missing, unknown, or stale evidence as unverified. Use existing verifier snapshots, structured reports, recovery and controller acceptance. Carry cross-Program history in a read-only handoff with real identities, not foreign basis_attempt_ids. This optional workflow adds no requirements to tasks that do not need host tools; G1/G2 and budget rules are unchanged.

## Outer Codex review and repair

The outer delivery session owns one scoped review of the agreed delivery; reuse an
equivalent review and inspect only changed/affected paths after repairs. A child
implements its assigned task and reports this attempt's evidence and increment;
the Harness controls execution, budgets and independent acceptance. Do not ask
every child to review the entire delivery or let a report certify acceptance.

Confirm an extra finding against the original requirement, current version,
reachable trigger, observable difference and counterevidence. Repair confirmed
in-scope defects automatically when the existing authority, a real repair entry,
budget and recheck path suffice. Explain disproved findings; retain uncertain ones;
optional improvements do not block delivery. Do not weaken protected checks.
Current unaccepted writable outputs may be repaired directly; an original Plan's
valid same-path replacement creates a new candidate. For an accepted producer use
an applicable native repair route or `request-build-repair`, preserving historical
PASS and the actual failure history. The latter supports CODEX responsibility and
its dependency rebuilds; a fixed LOCAL command does not gain reasoning ability.
Never edit accepted bytes to manufacture drift or forge a verifier failure.

Use `advance-build` with `advance_mode: ONE_ATTEMPT` when the outer session must
control this repair chain. After each return, use `read-build` to retrieve all
unmerged `implementation_commands`, not just `last_command`. A `final_message`
can be a short progress message even after multiple completed messages or an
interruption; it does not prove a complete handoff. For an actual gap, use the
bounded read-only recovery and round-merging method in the
[runtime contract](../../../docs/GENERIC_BUILD_RUNTIME.md).
Do not rerun/advance merely to recover a report. Preserve unresolved findings and
unknown counts rather than assume zero; missing history does not block a first
lawful repair or unrelated authorized work.

Keep the task's selected finite budget, cumulative failed rounds and pending
rounds in its existing work record; children report increments. Reopening with new
evidence, changing sessions, replaying requests or another finding's success does
not reset them. Success has no fixed item-count cap; real time/calls/attempts still
count. Merge a cumulative 1 then 2 as 2, settle an existing pending round once,
and do not equate command/attempt counts with failed product repairs. Only a native
settlement of `NOT_DISPATCHED` proves that implementation was not dispatched: it
adds no product repair failure and does not discredit the method, but keeps actual
attempt/time use. Missing observations or unknown effects keep their native hold.

Before the next CODEX attempt, pass relevant recovered history, selected limits,
pending rounds and the next method through `codex_handoff` on ONE_ATTEMPT. Bind it
to the actual receiving workpack and prior attempt IDs; a failing consumer may
hand off to its producer. A stored summary proves binding, not that a model read
or followed it. Recovery uses the started attempt's stored context; new summaries
are not queued. LOCAL tasks receive no model handoff or new service calls.

Stop continuing the same ineffective chain only when there is neither an effective
change nor new diagnostic progress, or the existing stopping condition applies.
A tested new hypothesis/reproduction condition may justify continuing without a
diff; cosmetic edits or repeated promises are not progress. Do not actively
dispatch successors depending on a known unresolved defect; normal diagnosis,
repair and unrelated authorized work may continue within scope and budget through
existing applicable entries. ONE_ATTEMPT does not add a task selector, revoke
approval, cancel running processes or control other callers/continuous mode.
Do not fabricate CONTRACT_GAP or command failure to stop the Harness. Native
independent-assertion repair retains its original contract and budget, separate
from the selected allowance for Codex's extra finding work.

Check the defect's targeted recheck, related regressions and the current version's
required independent results separately. Development checks awaiting the host are
pending, not success or infrastructure failure; children should return normally.
Original checks may remain green while an extra defect remains unresolved; report
both. Let the controller commit acceptance and demonstrate actual Harness use.
Stop when agreed delivery is met. Report which cases passed and remain unverified;
PLAN_CHECKS_ACCEPTED is not whole-PRD, installed-Harness or release acceptance.

All new builds use this route. Never fall back to retired Candidate/epoch workflows
or old authorization. Use read-history only for a named closed legacy authoring
database; it exposes historical data without migration or current permission.


## Public checker interfaces and explicit rebinding

Use the task's per-Case verification_interfaces and public acceptance_contracts.
Resource STRUCTURED_V1 writes FOUNDRY_REPORT_DIR/summary.json with actual identity,
all required checks and applicable service-stop/remote-effect accounting. Existing
non-resource exit-code or structured stdout interfaces remain valid. Reuse an
existing workdir/interpreter interface or resource environment; add only missing
bindings. Keep cwd and venv; a working sys.executable need not be replaced. The
optional test_execution adapter's parameter/environment names are not universal.
Public development adapters and host-owned independent checkers have distinct
responsibilities; private verifier:// references do not grant implementer reads.
The independent checker actually loads its declared frozen dependencies.

For explicit same-Program/same-database continuation, prepare may supply top-level
rebind_from. Preserve original budget ceilings and task/output/Job/dependency
identities; cumulative unique attempts retain old usage, including NOT_DISPATCHED.
Show this relationship in the existing Readback/approval flow. Fresh approval
supersedes the linked old scopes atomically, without inheriting old authority.
Unknown/in-flight effects still require reconciliation. Qualified unchanged
acceptance retains its original basis; changed checks reverify unchanged bytes
without rerunning implementation, counting real new attempts normally. Pending
reverification survives another explicit rebind. Real assertion failures retain
native product repair; old BLOCKED diagnostics do not automatically reblock the
new repaired scope. Readback separates cumulative and current-preparation usage,
reused_acceptance and reverification_pending. This is not cross-database migration,
arbitrary task renaming or a G1/G2 extension; ordinary preparation stays unchanged.

## Global model defaults and interrupted observations

When requested, prepare with `follow_codex_defaults: true`, `scope.model: null`
and no explicit effort. The native global config reader resolves model and
reasoning effort before approval. Show the frozen pair and returned source;
do not inherit global permissions, tools or provider configuration. Existing
prepared scopes keep their frozen values and cumulative budgets.

For an interrupted host, read first. `reconcile-build-observations` records
complete durable results without dispatch, acceptance or cleanup, even after
expiry/revocation. Missing captures remain missing. Only a trusted host's actual
termination/effects evidence plus a real user decision may use the existing
`resolve-build-attempt` route with `host_reconciliation`. Never infer safe replay
from a missing PID, elapsed time or partial stdout. Follow the CLI documentation;
this is not a new per-task approval gate.
