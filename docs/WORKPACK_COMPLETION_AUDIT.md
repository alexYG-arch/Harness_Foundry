# Workpack completion planning and evidence audit

Status: implemented read-only contract/evidence inspection, **not Workpack
acceptance, an independent semantic verifier, or authority to advance**.

## Interfaces

The packaged `tools/workpack_runtime.py` exposes:

| Command | Inputs | Result |
| --- | --- | --- |
| `completion-plan` | Candidate root, node ID, Workpack ID | Complete declared completion plan; exit 0 only means planning succeeded |
| `audit-completion` | The same inputs plus execution root | Evidence observations and unresolved requirements; incomplete audit exits 1 |

Use `--candidate-root`, `--node-id`, `--workpack-id`, and for the second command
`--execution-root`. Neither command dispatches a process/model, installs tools,
creates an Execution Root, writes a controller event or approves a result.
The execution root is a diagnostic read binding, not a generation-root override.
This route is not part of default core startup.

The planner reads Candidate inventory-bound DAG, Workpack, command/capsule and
task bundle files. It retains the entire native unit, ordered artifact set,
schemas, validation rules, Oracles, failure returns, predecessor nodes/prior
Workpacks, required capabilities and their declared source. Additional task
obligations, including the Lab protocol/CLI/fixture contract, remain in the
semantic scope. Checking only the structural result's schema cannot cover them.
Missing semantic bundles remain explicit; a generic structural plan is not
silently upgraded to a complete semantic contract.

`artifact_production_groups` separates task-executor artifacts from acceptance-
controller artifacts without removing anything from the required artifact set.
`WORKPACK_CONTROL_RESULT` belongs to `WORKPACK_ACCEPTANCE_CONTROLLER`, after
native command observations and independent Oracles. It is not a prerequisite
file for the coding task to manufacture. The entire Workpack/DAG still includes
its output domain; individual command scopes do not. The command manifest's
`workpack_acceptance_write_roots` is a planned controller domain, not an active
command grant. Coding and checked-project processes cannot write those roots.

## Implemented observations

Command evidence comes from matched `COMMAND_RESULT_OBSERVED` and
`TRANSITION_COMMITTED` records in the existing controller stream, bound to its
approved Parent, Candidate, native project/Workpack/command and recorded task.
An observed but uncommitted process is not reported as a committed command.
The same command ID in another Workpack does not satisfy this one. These are
historical process/model-turn observations, not proof of semantic completion,
all-Job coverage, command-order acceptance or fresh execution authority.
Agent-written result files and a stdout message saying PASS are not imported as
controller evidence.

`capability_observations` separately resolves required capabilities produced by
the committed startup actions. The observation, commit and derived grant must
name the same attempt, approved native Parent, Program and Candidate. The native
result must actually contain the capability and identify its declared source
node. Coding preflight consumes the same provenance reader. Existing command
observations also use this shared selection, retaining their own task and
process-result checks. Workpack-produced capabilities still report
`PROVIDER_NOT_IMPLEMENTED`: a coding turn or protocol PASS cannot supply them.
These records neither erase historical evidence when an old Parent expires nor
grant authority under that expired Parent. No additional hash layer is created.

For shared JSON artifacts the audit checks actual bytes against the declared
JSON Schema 2020-12 contract. Missing files, invalid instances, unsupported
representations/dialects and unresolvable schemas have distinct outcomes.
External schema retrieval is disabled. Optional dependencies are declared in
the plan and the Factory's `runtime-audit` extra: `jsonschema>=4.18,<5` and
`referencing>=0.28,<1`. The audit never installs them. If absent, schema evidence
remains unavailable. The default core still has no new dependency.
The portable Factory manifest declares the same optional routes and checks them
against `pyproject.toml`. Import discovery and manifest generation consume one
route declaration; adding an import allowlist entry alone cannot declare its
installation contract. A relocated CLI and the packaged audit are also tested
with Python site-packages disabled: core startup passes, while schema auditing
reports the missing dependency rather than producing a false PASS.

The diagnostic root binding does not grant a Job read lease. Job artifacts are
not opened by this route; they remain `JOB_READ_LEASE_REQUIRED` until a current,
authority-bound reader supplies their bytes. No broad execution-root read is
used to bypass the per-Job contract.

## Controller read isolation

SQLite's WAL mode can require writable auxiliary files even for a read-only
connection, and committed changes can reside in the WAL rather than the main
database. See the official [WAL documentation](https://www.sqlite.org/wal.html)
and [WAL file format](https://www.sqlite.org/walformat.html).

The audit does not open the source database through SQLite. It copies the main
file and any WAL into a disposable host temporary directory, checks that source
file identity/size/modification metadata did not change across the copy, then
opens and verifies the copied event stream. SQLite's index/temporary effects
stay in that directory and are discarded. It never deletes/checkpoints source
sidecars or labels the live source immutable. Detected concurrent change makes
the diagnostic unavailable, not PASS and not a retry authorization.

This is a stable-file-set diagnostic copy, **not a transactionally locked live
backup, recovery source or current authority snapshot**. It is never consumed
by the runtime's authorization/commit checks. The result separately reports
temporary snapshot use and zero Candidate/execution/controller-event writes;
it does not claim that no host temporary files were created.

## Remaining acceptance work

Every current audit is `WORKPACK_EVIDENCE_INCOMPLETE`. Even if all inspected
schemas pass and command observations exist, semantic validation and independent
Oracles remain `NOT_EVALUATED`. `workpack_accepted` is false, no produced
capability is granted and no successor starts. The full retained semantic
contract defines the missing scope rather than hiding it behind a green check.

The native `LAB-PROTOCOL-CHECK` now invokes the project's actual protocol API and
stores independent behavior observations through the approved offline receiver;
see [protocol support](LAB_PROTOCOL_SUPPORT.md). Its scope is protocol primitives,
not full Workpack acceptance. This audit conservatively still classifies command
rows as process observations; it does not promote the nested protocol report to
an artifact Oracle or a fresh implementation attestation.

Next, complete the independent Workpack verifier for the remaining obligations,
including the Lab implementation/self-tests, artifact validation/Oracles,
Workpack-produced capability provenance, Job lease reads, and failure returns. Only
its actual verified results may feed the existing controller's Workpack
acceptance transition. Neither this inspection interface nor test fixtures
replace that provider or close Lab/Linkage/Harness/video acceptance.

Structural-result ownership is now explicit in the producer, coding prompt,
completion plan and both static Validators. Five regressions cover exclusion
from coding writes, preservation of every required artifact and business write
scope, both normal static projections, owner/timing relabeling, and reintroduced
receipt writes. This repairs a producer dependency cycle, not the remaining
runtime acceptance implementation. That controller must still bind current
implementation/evidence bytes, verify the complete owned semantic scope and
required capabilities, then publish its result and select an eligible successor.
The protocol report does not certify those remaining obligations.
