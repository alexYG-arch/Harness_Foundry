# Lab protocol implementation support

Status: executable pure protocol primitives and independently defined behavior
probes are implemented and packaged. A Candidate-owned command runs both those
probes and the complete frozen Registry/Schema declaration checks against the
selected project's API through the existing offline receiver.
This is **not a complete external Lab, a Workpack acceptance adapter, or permission
to execute target code without the separate runtime approval**.

## Implementation rather than declared PASS

The portable `harness_foundry_runtime.lab_protocol` library implements:

| API | Behavior |
| --- | --- |
| `validate_instance` | Actual JSON Schema 2020-12 schema/instance validation; no remote schema retrieval |
| `load_evaluator_registry`, `resolve_evaluator` | Copy and look up frozen evaluator declarations; do not import their Python entrypoints |
| `require_operator` | Require an exact registered name; reject an unknown operator |
| `resolve_evidence_bytes` | Exact lookup of already captured bytes; no file reads, fallback, decoding or lease acquisition |
| `normalize_skill_url`, `derive_job_id` | Normalize the public repository URL and apply the declared immutable-identity algorithm |
| `specialize_artifact_schema` | Deep-copy and bind Job/source fields while preserving renderer identity and other schema constraints |

Schema binding was extracted from the existing producer into this standalone
library. The producer uses the same implementation, avoiding a second subtly
different binding algorithm in the built Lab. That sharing is not independent
Oracle evidence. The separate `lab_protocol_checks.verify_protocol_primitives`
suite uses explicitly defined expected outcomes, not the producer or the
implementation's own self-report, to call actual behavior. It checks both valid
and invalid requests, unknown lookup cases, immutable identity, input preservation
and renderer/content separation. Deliberately stubbed APIs fail these probes.

The suite accepts the actual API object and the frozen public Job request schema.
`LAB-PROTOCOL-CHECK` is now a native command after `LAB-CODEX-CODING` in the
`LAB-PROTOCOL` Workpack. Its frozen recipe runs `tools/lab_protocol_worker.py`
against the selected repository's `external_lab/protocol.py`. Missing or broken
project code cannot fall back to checking the shipped support library. The
project can deliberately reuse that library, but must expose its own API entry.
Project imports and API calls occur only in the child, never in the controller.

`tools/workpack_runtime.py verification-plan` retains the complete native
Workpack completion plan and supplies the frozen argument tail. Planning does
not create directories, run imports or confer authority. Runtime hydration may
bind the already approved Python resource; it cannot replace the worker,
project or schema with `python --version` or a project-authored self-test.

The existing offline Parent, durable Grant and process receiver are reused.
Both approval preparation and dispatch compare the current Candidate command.
Dispatch additionally requires its actual prior coding observation and commit.
The verifier has no workload write roots: stdout is captured by the supervisor
and stored in the existing controller event stream. A valid result requires
successful finite process capture, the complete ordered 28-case primitive set,
the complete frozen-declaration set and all behavior outcomes; a bare stdout
PASS is not evidence. These are protocol-only
observations. Hydration removes inherited successors/retries and Parent
validation rejects their reintroduction. No Workpack capability is granted.

The `LAB_PROTOCOL_BEHAVIOR_V2` recipe additionally binds the Candidate's frozen
evaluator registry and Requirement schema catalog. The controller derives the
expected Case IDs from those Candidate inputs before dispatch; it never trusts
the project's proposed case list. The independent worker loads every evaluator,
resolves each full declaration and specializes every declared schema with two
distinct synthetic Job identities. It checks schema validity, unchanged inputs,
preserved non-binding constraints and separate renderer/content identities.
Both omitted members and misleading success reports fail verification.

The optional catalog can legitimately be absent when contracts are supplied
directly per Atom. In that case the empty catalog is explicit context for the
binding-set check, not evidence that per-Atom artifact Oracles ran. Both input
forms have actual worker regressions. Frozen-declaration checks never resolve
real Git sources, execute evaluator algorithms or recompile a Job graph; their
report carries those exclusions and `workpack_accepted=false`.

Temporary tests cover real worker subprocesses and a TEST-only coding/receiver
fixture, without calling a model. A separate opt-in test uses the actual offline
OS sandbox to verify normal behavior and denial of implementation-file rewrites.
Its explicit host Python dependency reads are test/runtime bindings, not a new
portable default or an installation permission. Recovery consumes a previously
observed result without rerunning changed project code; that historical result
does not attest to the current implementation bytes or satisfy fresh acceptance.

JSON Schema support uses the existing optional `runtime-audit` dependencies.
Importing the protocol and running its standard-library operations needs no
optional install. Missing schema dependencies are unavailable/inconclusive, not
an invalid-instance result or successful negative test. No function installs a
dependency, accesses the network or modifies runtime authority.

## Concrete schema loading repair

The first actual probe reproduced a producer defect: the embedded public request
schema used a non-empty JSON pointer fragment as `$id`. JSON Schema 2020-12
forbids non-empty fragments in that canonical identifier. The producer now emits
`urn:harness-foundry:public-skill-job-request:v1`; the interface's existing JSON
pointer remains a locator, not the canonical schema ID. Both the independent
interface validator and real metaschema regression reject the old form. See
[JSON Schema Core 8.2.1](https://json-schema.org/draft/2020-12/json-schema-core#name-the-id-keyword).

## Phase ownership and remaining chain

Each Lab Task Bundle now names the owner and exact references of its current
implementation obligations. Shared command IDs, CLI interfaces, evaluator IDs
and registry protocols remain complete context. They are not assertions that a
later Workpack has already completed. Current artifact contracts and prerequisites
remain required. The independent phase validator rejects changed owners, omitted
obligations or reclassifying implementation obligations as shared context.

`LAB-PROTOCOL` and `LAB-CLI` bind the shipped support library and probe suite.
The support scope does not cover full dynamic artifact-graph recompilation,
evaluator algorithms, Job leases, command receipts or Workpack acceptance. A
synthetically supplied source identity is not a source-resolution attestation;
captured bytes are not a read lease. Those distinctions are not optional.

The native command and real protocol observation are implemented. Remaining
integration must verify the full owned semantic/artifact scope, predecessor
capability provenance and current implementation/evidence bytes, then produce
genuine Workpack acceptance before unlocking the next coding stage. The read-only
completion audit still reports those unresolved requirements. Protocol probe
PASS alone cannot satisfy the structural result's independent acceptance Oracle.
