# Audited pre-build delegation V1

Opt-in v2.9 protocol extension approved by the user in the current task. The
pinned v2.8 snapshot is unchanged. Existing Programs do not acquire a grant or
change their human approval records merely by upgrading the Factory.

## Scope and authority

The 2026-09-19 [upstream build-document policy](GENERIC_BUILD_PLAN.md) applies
before all Harness build authoring. Clarification must produce a displayed build
document and actual human confirmation before entering Foundry. This review is
not delegated by this protocol, even under an active historical grant. Existing
grant/approval records remain unchanged; they do not prove the new review took
place. Compatibility authoring now rechecks the stored full document before
advancing, including delegated requests. Only a real human REOPEN can supply a
new document-review record. Revocation remains available when a document is stale.

A human grants `PREBUILD_AUTHORING_AND_CANDIDATE_DECISION` to one Program and
Chat. The grant binds the current Requirement, authored intent, source registry,
specification identity, and output naming rule. It permits internal authoring,
REOPEN, deterministic empty output binding, Requirement/Architecture locks,
Candidate generation, review and a delegated Candidate decision. It ends on
Candidate approval or human revocation. IDs cannot be reused or reactivated.

This changes the legacy Requirement/Architecture lock and Candidate decision
requirements **only for the opted-in path**, not the upstream build-document
Human Review. It does not reinterpret a delegate as HUMAN_VIA_CODEX_CHAT.
Candidate decisions use `approval_mode=DELEGATED`; the old human approval field
is not changed to APPROVED. Source conflict resolution, changed authored goals,
new sources, execution/installation, and arbitrary output overrides are not
delegated. Repairing the Factory Producer remains ordinary authorized source
engineering, not target Workpack execution.

Actual Harness construction/execution is outside this protocol. Approval stops
at `PREBUILD_APPROVED_EXECUTION_NOT_AUTHORIZED`, with
`HARNESS_EXECUTION_AUTHORIZATION_REQUIRED`. No Execution Root, Driver, Workpack,
installation, model download or media generation is started.

## Commands and payloads

All mutations use the existing `chat-turn` envelope, CAS, idempotency key and
Program-owned SQLite event store. No second journal or signing system is added.

| Intent | Actor | Exact payload fields |
| --- | --- | --- |
| GRANT_PREBUILD_DELEGATION | Human | delegation_id, decision=APPROVE, scope=PREBUILD_AUTHORING_AND_CANDIDATE_DECISION, requirement_ir_sha256, approval_text |
| REVOKE_PREBUILD_DELEGATION | Human | delegation_id, reason |
| REOPEN | Delegate | reason |
| BIND_DELEGATED_OUTPUT | Delegate | empty object |
| PREPARE_READBACK / ADVANCE_AUTHORING_UNTIL_GATE | Delegate | empty object |
| DELEGATED_FREEZE | Delegate | decision=APPROVE, requirement_ir_sha256, readback_sha256 |
| PREPARE_ARCHITECTURE_READBACK | Delegate | empty object |
| DELEGATED_ARCHITECTURE_LOCK | Delegate | decision=APPROVE, architecture_readback_sha256 |
| GENERATE | Delegate | empty object |
| REVIEW_CANDIDATE | Delegate | decision=APPROVE or REJECT, candidate_content_sha256, requirement_ir_sha256, review |

Delegate actors retain `chat_thread_id` and an actual agent action `turn_id`,
and add `type=CODEX_DELEGATED_AGENT` and `delegation_id`. Human grant actors use
the actual user turn and approval text; approval cannot be inferred from an
Agent summary. Neither delegated lock accepts or fabricates a human token.
The old REQUEST/CONFIRM human challenge path is unchanged.

The output rule retains the parent and base name of the already bound output,
removes a trailing `-epochN`, and appends the new `-epochN`. Binding requires an
absent path, creates nothing, and cannot override the parent or execution root.
Generation consumes that exact frozen binding and retains existing protected-root
and publication checks. An occupied path is not deleted or silently replaced.

`review` contains a nonempty summary, inspected Candidate file refs, and findings.
Each finding has code, message and boolean `blocking`. APPROVE requires a fresh
official Candidate validation PASS, unchanged published bytes and Requirement,
and no blocking findings. Static validation alone does not create a review or
an approval. REJECT retains the grant for repair; REOPEN invalidates the prior
decision without touching the old Candidate files.

## Evidence and compatibility

`readback` exposes `prebuild_delegations`, `candidate_decision` and
`delegated_next_allowed_intents`. `status` exposes delegated next actions without
changing the legacy human next-intent list. The public bounded authoring helper
uses the active delegate's identity on opted-in Programs; revocation never falls
back to a synthetic human actor. It does not automatically decide substantive
review findings.

`verify-run` checks the existing byte/event chain and independently audits prior
human grant, delegated identity, scope and non-execution provenance. Candidate
approval is a Program-local decision outside the immutable package. The decision
event binds its Candidate digest and must be provided separately to any later
explicitly authorized execution workflow; it is not a runtime authorization.

Regression coverage includes the unchanged human path, delegated locks, schema
parsing, stale/scope/revocation rejection, collision preservation, audit relation
failures, terminal stop and real temporary Candidate publication/review. Test
fixtures do not approve the user's production Candidate.

## Read-only execution handoff

`python3 tools/hffactory.py prepare-execution-handoff --program-id <program_id> --json`
reads the Program-owned store and current published Candidate. It returns a
`FACTORY_CANDIDATE_APPROVAL_PROJECTION_V1` only for an audited, current delegated
approval backed by its completed grant. It never reactivates that grant. A
missing decision, REOPEN, changed Candidate bytes, failed current validation or
missing startup provider blocks the handoff. There is no output-root override.

The receipt retains `approval_mode=DELEGATED`, the actual actor, decision event,
grant event, Requirement binding and Factory revision. The compatibility path
`evidence/engineering_dag/START_PACKAGE_HUMAN_APPROVAL/result.json` and the first
control action's legacy `human_approval_receipt_sha256` field do **not** turn the
decision into Human approval. The old Candidate human-approval field stays
unchanged. All execution, Driver, Workpack and installation permissions remain
false. The command prints the projection; it does not write a receipt or create
an Execution Root.

The existing runtime field `candidate_tree_sha256` identifies the portable
file inventory (`candidate_identity_domain=PORTABLE_FILE_MANIFEST_FILES`).
`factory_candidate_content_sha256` separately identifies the Factory publication
tree. These are distinct existing digest domains, not interchangeable values or
new authority mechanisms.

A future explicitly authorized runtime controller must call
`validate_live_handoff` against the authoritative Factory before consuming this
projection and supply its separate execution authorization. A saved projection
alone is not a bearer grant. That production controller integration is not yet
implemented; this interface is only the read-only half of the bridge.

`tests/test_execution_handoff.py` exercises real temporary authoring, generation,
review, the public CLI and the generated first-control action without compiler
or Validator mocks. The action accepts the delegated approval receipt together
with a separate test-only execution authorization, and rejects the receipt when
offered as execution authorization. This is protocol integration evidence, not
authorization or execution of a production Program.
