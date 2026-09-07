# Lab protocol implementation support

Status: executable pure protocol primitives and independently defined behavior
probes are implemented and packaged. This is **not a built external Lab, a
Workpack acceptance adapter, or permission to execute target code**.

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
A future execution adapter must invoke it inside an authorized isolated worker
with the selected project's implementation, never import untrusted project code
into the controller. Present tests invoke the shipped library in temporary
packaged Candidates, not code produced by a model or a formal target Workpack.

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

The next integration dependency is a Candidate-native independent verification
command that runs the selected implementation and the full owned verification
scope under an approved local Parent, then commits its real observation. Only
verified Workpack results and prerequisite provenance may unlock the next coding
stage in the existing SQLite controller. Protocol probe PASS alone cannot do so.
