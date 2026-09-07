# Coding command protocol boundary

Status: implemented planning, capture classification and the first post-startup
coding-stage adapter. Verified with a TEST-only subprocess, **not a live model
request, target execution authority or Workpack acceptance**.

## Read a declared coding task

The packaged `tools/workpack_runtime.py coding-plan` command selects a DAG node,
project Workpack and native `CODEX_CODING_AGENT` command. It reads the existing
Candidate inventory and task bundle; it does not create an Execution Root,
hydrate an executable, record a grant, invoke Codex or start a predecessor.

Required arguments are `--candidate-root`, `--node-id`, `--workpack-id` and
`--command-id`. Supply `--job-id` only when the native command requires one
selected Job lease. For the first Lab task the identities are `LAB_BOOTSTRAP`,
`LAB-PROTOCOL` and `LAB-CODEX-CODING`.

The result retains the entire selected Workpack, command, capsule and task
bundle, including artifact schemas, independent Oracle rules and failure
returns. It also retains the native effective read/write roots and selected Job
scope, DAG predecessors, earlier Workpacks within the node and earlier commands
within the Workpack. Those are declared prerequisites, not proof of completion.
The stdin prompt is a projection of that data, not a source of authorization.

The explicit-production semantic profile supplies these task bundles. A
structural-only compatibility Candidate, or a root materialization Workpack
without a bundle, returns `CODING_TASK_BUNDLE_REQUIRED`. It is not upgraded to a
semantic task by inventing a prompt or relaxing its Validator. This boundary is
intentional and tested separately from a normally compiled semantic Candidate;
neither compilation injects historical startup execution contracts.

## Observe one model turn

`coding_protocol.observe_coding_process` consumes captured stdout bytes, actual
exit status and capture timeout/truncation flags. It recognizes the documented
single-thread, single-turn JSONL lifecycle. A complete turn with a successful
process exit returns `MODEL_TURN_COMPLETED`, never a Workpack `PASS`.

| Observation | Disposition |
| --- | --- |
| Complete single turn and process exit zero | Model turn completed; artifact acceptance still required |
| Process nonzero or explicit error/failed turn | Model process failed; earlier effects may exist |
| Missing/malformed/unsupported lifecycle, lost exit status, truncated capture or timeout | Outcome unresolved; no automatic redispatch |

Agent messages and usage remain reported data. A tool error that the agent
subsequently recovers remains visible in `reported_command_failures`; it does
not by itself negate a later completed model turn. Neither a message saying
`PASS`, valid JSON nor exit zero satisfies the independent Workpack Oracle.
Supplying fabricated stdout to this pure classifier cannot create a durable
receipt or grant: a production adapter must own the capture and associate it
with its previously reserved SQLite attempt. The adapter below owns that capture;
no old offline process command is relabeled as a model command.

## Explicit model-service adapter

The installed CLI was inspected read-only using `--version`, `exec --help` and
`features list` (0.153.3). Its stdin/JSONL interface agrees with the official
[non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode).
Those probes and the test JSONL fixtures are not actual model-generation tests.

`CODEX_CODING_SERVICE` uses the existing public Parent prepare/approve/revoke and
advance/checkpoint/resume operations. Its command class is
`CODEX_CODING_MODEL_TURN`, with one durable reserved attempt, captured observation
and commit in the same SQLite event stream. Observation recovery does not
redispatch; an attempt without an observation remains unresolved. There is no
automatic retry or `resume --last`. A model-stage `PASS` only commits the completed
turn: the result schema requires `workpack_accepted=false`, no successor or
Workpack capability is emitted, and independent artifact acceptance remains due.

`coding_execution` binds the actual executable and its byte identity, complete
Candidate-derived task, runtime resources, native read/write and selected Job
scope, model, client state root, timeout and per-stream capture retention limit.
The separate coding Parent explicitly discloses model/auth/client service
traffic, access to saved client authentication and possible client-state writes.
Offline or startup Parents are not widened; pre-build delegates cannot approve
this Parent. `model=null` means the installed client's default, not a pinned
model. Parent limits bound attempts/transitions, not model tokens or billing.

The adapter first verifies committed SQLite-owned startup evidence and the
Candidate-native predecessor order. This slice supports only the first
post-startup coding task. Tasks with earlier Workpacks/commands return
`CODING_PREDECESSOR_ACCEPTANCE_REQUIRED` until the independent acceptance
provider exists. The full DAG and selected-Job dispatch are not live-validated.

The client receives UTF-8 stdin, JSONL output mode and a fresh explicit local
permission profile. Stdin retains the original task projection and adds a host
context mapping only its effective logical read/write roots to resolved local
paths, plus cwd and Job identity. This lets the model locate real inputs without
rewriting portable contracts or exposing the Factory/authentication paths.
Shells inherit no caller secrets; local command network is
denied. Optional apps, plugins, hooks, agents, browser/Computer Use, ImageGen and
unbounded connection retries are disabled. The user config is excluded without
editing it. Non-empty system/project config layers currently require explicit
configuration hydration and are rejected, not merged or silently ignored.
Managed requirements/rules remain in effect. This is a restricted supported
configuration, not support for every Codex deployment or account setup.

An offline receiver-capability probe precedes any model dispatch. Immediately
after the probes, the adapter checks current Parent/Grant/Factory bindings and
executable bytes again. No sandbox fallback is used. The process has a finite
timeout; timeout, malformed or truncated output is unresolved, never retry
permission. Capture limits bound retained evidence per stream, not temporary
spool-file growth. `--ephemeral` avoids session rollout persistence but does not
promise zero authentication/client-state writes. Only POSIX hosts are supported.

Do not describe a model request as offline because generated shell commands
use a network-denied sandbox. Official
[permission-profile documentation](https://learn.chatgpt.com/docs/permissions#scope-and-enforcement)
states that model/auth service requests, apps, MCP, browser and Computer Use are
outside the local command network policy. Effective configuration must therefore
be checked before an authorized live model run. In particular, older sandbox
settings can take precedence over permission profiles; merely adding a profile
argument or testing `--help` does not establish the active permissions.

Regression fixtures use an explicitly fake Codex executable that emits TEST
events and writes temporary marker files. They test stdin, process observation,
public authorization, ordering and recovery; they do not prove actual model
generation, service access or sandbox enforcement. Real offline Codex sandbox
tests cover the shared local receiver separately, without a model request.

No user configuration, account credentials, model selection or managed policy
was changed during implementation. No new signature, hash ledger or authority
database was added. Live model validation and independent Workpack acceptance
remain required before claiming the Harness build is closed.
