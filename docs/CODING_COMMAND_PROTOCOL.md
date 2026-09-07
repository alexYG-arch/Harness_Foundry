# Coding command protocol boundary

Status: implemented input planning and capture classification; **no model
dispatch adapter, target execution authority or Workpack acceptance**.

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
with its previously reserved SQLite attempt. No such adapter is exposed by this
change, and no old offline process command is relabeled as a model command.

## Remaining transport integration

The installed CLI was inspected using only `--version` and `exec --help`
(0.153.3). Its stdin/JSONL interface agrees with the official
[non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode).
Those probes and the test JSONL fixtures are not actual model-generation tests.

The next transport slice must bind the actual executable, model/service/auth
scope, effective configuration, task inputs and Job scope in the existing
human-approved Parent, then reserve, dispatch and observe through the existing
SQLite engine. It must preserve native Workpack ordering and cannot replay an
unresolved attempt or use `resume --last` to guess its identity. Independent
artifact validation remains a separate successor to the model turn.

Do not describe a model request as offline because generated shell commands
use a network-denied sandbox. Official
[permission-profile documentation](https://learn.chatgpt.com/docs/permissions#scope-and-enforcement)
states that model/auth service requests, apps, MCP, browser and Computer Use are
outside the local command network policy. Effective configuration must therefore
be checked before an authorized live model run. In particular, older sandbox
settings can take precedence over permission profiles; merely adding a profile
argument or testing `--help` does not establish the active permissions.

No user configuration, account credentials, model selection or managed policy
was changed. No new signature, hash ledger or authority database was added.
