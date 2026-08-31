# Harness Foundry v2.9 v0_22 Human Review

## Review boundary

- Candidate: `Harness_Foundry_v2_9_Start_Package_Candidate_v0_22`
- Review mode: read-only Human Review; Human Gate was not approved.
- Execution Root: not created.
- Driver, Workpack, runtime authorization and release commit: not started.
- Historical Candidate v0_22 and the original adversarial evidence remain immutable inputs to the replacement epoch.

## Release-blocking findings

### HR-V022-001 — Authority Normalization lacked a semantic dual-Oracle closure

The producer correctly converted the declared source authority
`HUMAN_VIA_CODEX_CHAT_REVIEW_EVIDENCE` into the portable canonical value
`HUMAN_VIA_CODEX_CHAT`, while retaining `declared_authority_level`. However,
the Factory Validator only checked that the portable value belonged to an
allow-list, and the standalone self-check did not compare the compiled source
with the frozen declaration.

Two synchronized-rehash attacks therefore passed both checks:

1. remove `declared_authority_level`, then recompute dependent Hashes;
2. relabel both authority fields, then recompute dependent Hashes.

Required closure: the producer, standalone Oracle and Factory Oracle must each
implement the normalization semantics independently. Both Oracles must compare
source identity, payload Hash, copy policy, declared authority and canonical
authority against `FROZEN_REQUIREMENT_IR.json` and fail closed on unknown or
altered values.

### HR-V022-002 — v0_21 generation remediation was omitted from closure

`target.v0_21_generation_failure_remediation` remained a required replacement
obligation, but the Closure Receipt selector only included keys named
`human_review_*_closure`. The receipt could report PASS without an explicit
entry for the generation failure and its authority-normalization repair.

Required closure: support an explicit typed `closure_receipt_required` marker,
bind the complete requirement object by canonical Hash, include its finding IDs
and evidence, and require both Oracles to reject omission or alteration.

### HR-V022-003 — signed release authorization Hashes were not compared with live authority

The production adapter required syntactically valid SHA-256 values for
Candidate content, Requirement IR, Executor release and Human Gate receipt, but
did not compare them with authoritative actual values. A valid authority
signature could therefore bind four wrong but well-formed Hashes.

Required closure: place the four actual Hashes in the authoritative
`CURRENT_STATE_COMMITTED` event, derive them through the Hash-bound Event Store
adapter, and compare the signed authorization with those live values inside the
same `BEGIN IMMEDIATE` transaction before authorization consumption and release
commit.

## Required adversarial coverage

- synchronized rehash after removing the declared source authority;
- synchronized rehash after relabeling both authority fields;
- valid authority signature with wrong Candidate content Hash;
- valid authority signature with wrong Requirement IR Hash;
- valid authority signature with wrong Executor release Hash;
- valid authority signature with wrong Human Gate receipt Hash.

Each case must be rejected by the applicable production code and by the two
semantically independent Oracle paths. Source-code equality alone is integrity
evidence, not independent semantic proof.

## Replacement and non-claims

The replacement target is v0_23, but Candidate generation remains prohibited
until a later explicit exact absent-root binding, Requirement Readback and
human-confirmed Requirement Freeze. This review does not create an Execution
Root, consume a Human Gate, grant runtime authority, execute a transition,
start a Driver or Workpack, install, publish, release or certify v2.9.
