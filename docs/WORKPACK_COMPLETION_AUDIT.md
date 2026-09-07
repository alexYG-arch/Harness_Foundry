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
predecessor capability provenance, Job lease reads, and failure returns. Only
its actual verified results may feed the existing controller's Workpack
acceptance transition. Neither this inspection interface nor test fixtures
replace that provider or close Lab/Linkage/Harness/video acceptance.

The next producer/acceptance dependency is structural-result ownership. The
current `task_bundle_for_workpack` fallback places `WORKPACK_CONTROL_RESULT`
among coding-visible artifact obligations, but its production rule requires
completed command receipts and its Oracle excludes target self-report. Those
results must be published by the post-observation acceptance controller, not
used as a prerequisite for the coding command that precedes verification.
The follow-on implementation must separate implementation outputs from these
acceptance-owned outputs, retain the complete Workpack obligation set, bind
current implementation/evidence bytes, and prove required capabilities before
publishing a result or selecting a successor. The protocol report added here
does not silently resolve that ownership or certify the remaining obligations.
