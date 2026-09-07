# Local runtime authorization

This is an opt-in runtime interface, separate from Factory authoring and the
41-capability default core route. It supports the implemented Candidate-native
startup and offline local process plans. It does not provide a model transport,
start a Driver, run a Workpack, install tools or approve the target's outputs.

An audited pre-build Candidate decision is an input, not a runtime grant. A
trusted Codex Chat host must obtain and accurately carry a separate human
decision. The CLI validates its recorded identity and exact challenge binding;
it does not authenticate a chat transcript or prove that someone read a screen.
Do not submit synthetic human decisions outside explicitly labeled tests.

## Three public operations

Each command takes `--request REQUEST_JSON --control-db APPROVED_CONTROL_DB
--json`. Request files are local operator inputs, not portable Candidate files.
The database argument must exactly match the plan's canonical absolute
`execution_root/.harness-foundry/control.sqlite3`; it is not a root override.

| Command | Request fields | Effect |
| --- | --- | --- |
| `prepare-runtime-authorization` | `parent` | Read-only live binding checks and complete readable challenge |
| `approve-runtime-authorization` | `parent`, `challenge`, `approval` | Initialize native controller if needed and record the approved Parent; no command execution |
| `revoke-runtime-authorization` | `program_id`, `parent_authorization_id`, `revoked_by`, `reason` | Append an audited revocation; no command execution |

## Prepare and approve

The host constructs the existing Parent Risk Envelope from the approved
Candidate/handoff and actual operator-selected roots, commands, scopes, budgets
and expiry. Do not ask the user to calculate hashes or author per-attempt leases.
`startup_transitions` derives the three native startup contracts; the existing
local process binder retains each selected native command and Job lease.

The Parent contains `startup_execution`, `local_execution`, or both. Both plans,
when present, must refer to the same Candidate, Factory locator, execution root
and controller. The public interface requires the actual
`FACTORY_APPROVED_START_PACKAGE` binding and its live audited decision, retaining
null Architecture/Control epochs where the Requirement left them unbound.

Readback creates no root, database, grant, receipt file or command attempt. Its
challenge discloses the complete plans, read/write roots, budgets and expiry,
plus controller effects: possible execution-root/database creation and Parent
registration. A proposed Parent's `GRANTED` wire status is not active authority;
only the subsequent approved event grants it.

After the human approves that exact scope, submit the unchanged Parent and
returned `challenge`. `approval` contains `decision=APPROVE`, the returned
`challenge_sha256`, `approved_at` as the actual timezone-aware decision time,
and `approved_by` with `type=HUMAN_VIA_CODEX_CHAT`, actual `chat_thread_id` and
actual `turn_id`. No fabricated later turn, delegated actor relabelling or
caller-supplied runtime clock is accepted. The digest is machine-carried; this
does not add a manual child-hash confirmation workflow.

Decision validation, current expiry and live Factory/Candidate checks occur
before initialization. Another live check precedes grant registration. Writable
roots cannot overlap Candidate, Factory implementation or authoring storage.
Read-only Factory path aliases retain their approved spelling and are resolved
for overlap checks. Runtime write paths must remain canonical and unlinked.

Approval reuses the existing kernel receipt and `PARENT_AUTHORIZATION_GRANTED`
event. A native empty database left after interrupted initialization can resume.
An incompatible database is not overwritten or converted. A controller already
containing another Program is rejected, with the ownership check repeated inside
the same SQLite transaction as grant registration. This does not change the
generic core store's optional multi-Program use outside this local route.

Successful registration returns `RUNTIME_PARENT_APPROVED_EXECUTION_NOT_STARTED`.
Repeating the same still-valid decision returns `RUNTIME_PARENT_ALREADY_APPROVED`
without another grant event. The same authorization ID cannot identify a changed
decision or reactivate a revoked Parent. Non-native/legacy control history is not
automatically adopted. Initialization failure may leave an empty native store;
it is not an atomic transaction spanning filesystem creation and Factory state.

## Dispatch and revoke

The existing `advance-until-gate`, `checkpoint` and `resume` commands remain
separate operations. They consume the approved Parent and revalidate current
scope and Factory bindings. Native startup stops before Lab; an offline process
success does not satisfy a whole Workpack or project acceptance contract.

Revocation takes an actual human identity in `revoked_by` and a non-empty reason.
Both are retained in the existing SQLite revocation event. It remains available
after Parent expiry or Factory REOPEN; making a grant unusable must not prevent
its cancellation. Repeating revocation is read-only. Revocation prevents future
dispatch/commit through the kernel, but does not terminate an already running OS
process or undo its effects. The result explicitly reports that distinction.

No command here edits a frozen Candidate, grants fresh authoring permission,
reuses a completed pre-build delegation or supplies target execution evidence.
