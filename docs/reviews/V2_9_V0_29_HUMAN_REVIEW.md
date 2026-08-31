# Harness Foundry v2.9 v0_29 Human Review

## Review decision

`BLOCK_START_PACKAGE_HUMAN_GATE`

This was a read-only Human Review of the published v0_29 Candidate. The review
did not approve or consume a Human Gate, create an Execution Root, start a
Driver or Workpack, grant authority, or execute a runtime transition. The
v0_29 Candidate remains immutable historical evidence.

## Reviewed identity

- Program: `PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE`
- Candidate: `candidate-v0_29`
- Candidate content SHA-256: `ac601217edbb7141a0a1be9e44d0977ea6f9bfd0e4c554e67c0736183db14c28`
- Candidate file count: `323`
- Factory-frozen Requirement IR SHA-256: `cfef882c903475aa7d0fcef812aefae73a4c5dc25e1660ff31a19a95f6be2960`
- Portable Candidate Requirement IR file SHA-256: `c6223a08007aa92ccc060e7053a155abe09b958872eba113e3bbd40ee6a48777`
- Review input Factory revision: `224`
- Review input Factory state SHA-256: `2c95c102030169746a4df8fca4eceb6b9961587ae0c1fba6041e97b9b5130880`
- Reopened Requirement Epoch: `30`

## Blocking finding

### HR-V029-001 — validation-report Authority provenance was not integrity-bound

v0_29 correctly made both Factory external Oracles fail closed when their
authoritative Source Registry or Requirement IR input was absent. It also wrote
`authority_input` and complete Event Store `authority_provenance` into the
Candidate Validation Report. However, those fields were only copied into a
late-bound report; neither Oracle compared the embedded fields with its fresh
result, and the portable manifest deliberately excluded the report.

A read-only adversarial copy of v0_29 removed `authority_input` and
`authority_provenance` from both embedded external-Oracle entries. With the
revision-224 Factory authority inputs, the Factory Validator still returned
`PASS`. With a valid receiver-side signed Source Authority Policy, the
standalone self-check also returned `PASS`. The Candidate could therefore lose
the provenance evidence while all Candidate-controlled Hashes continued to
look valid.

The root cause was a late-output trust gap:

1. the Factory generated the report after its main validation pass;
2. the report was excluded from the portable inventory to avoid a Hash cycle;
3. no non-circular detached receipt bound its exact bytes;
4. the Factory checked only the report's overall status and non-claims, not the
   complete external-Oracle projections;
5. the receiver-signed policy bound source and release-history authority, but
   not the report or a detached report receipt.

## Required replacement closure

Requirement Epoch 30 and replacement v0_30 must:

1. compare each embedded external-Oracle entry with the Factory's freshly
   recomputed entry, including exact fields, authority input, Event Store
   revision, tip and content Hashes;
2. reject missing, incorrect, extra, exchanged or stale provenance;
3. generate a non-circular detached Validation Report Receipt that binds the
   exact report bytes and the sorted external-Oracle projection;
4. include that receipt in Human Review closure evidence and the portable file
   manifest while continuing to exclude the report itself from the circular
   manifest;
5. require the receiver-pinned signed Source Authority Policy to bind the exact
   report and detached-receipt file Hashes;
6. make standalone reject report or receipt deletion, report mutation, and
   synchronized Candidate-local re-Hashing;
7. activate this new mandatory contract only at Requirement Epoch 30, so v2.8
   and earlier v2.9 routes are not retroactively assigned a new authority gate;
8. preserve v0_29 and this review evidence without creating v0_30 roots or
   granting any execution authority.

