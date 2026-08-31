# Harness Foundry v2.9 v0_27 Human Review

## Review decision

`BLOCK_START_PACKAGE_HUMAN_GATE`

This was a read-only Human Review of the published v0_27 Candidate. The review
did not approve or consume a Human Gate, create an Execution Root, start a
Driver or Workpack, grant authority, or execute a runtime transition. The
Candidate directory was retained byte-for-byte as historical evidence.

## Reviewed identity

- Program: `PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE`
- Candidate: `candidate-v0_27`
- Candidate content SHA-256: `cd3f7607a8f081c8b453e398eaaa54fa5edcf5bad6b3b2c37a67813cf651a335`
- Frozen source Requirement IR SHA-256: `509ad20773a2a2a9f17c882d4207757c7df57d2afd77a25de3d7ad12b31f5eaa`
- Review input Factory revision: `208`
- Review input Factory state SHA-256: `c344cc49b00fa6e23b8409c7d29fedc63d1fb0f936bdac4d8d914bbc52d678ed`

## Blocking finding

### HR-V027-001 — historical successor identity has no external authority

v0_27 cross-checks `replacement_candidate`,
`successor_binding.candidate_version`, the generated Closure Receipt, current
Package Identity and Requirement Epoch. Those checks reject a one-field
identity mutation, but every expected value still originates inside the same
Candidate-controlled Frozen Requirement IR.

A read-only adversarial test changed the v0_25 closure from successor v0_26 to
v0_27, changed its replacement identity and Closure Receipt to the same value,
and recomputed the closure and portable Requirement Hashes. Both the actual
Candidate standalone closure checker and the Factory
`_check_dag_containment_and_closure` checker returned no findings. Therefore
the two checks establish internal agreement, not the historical fact that the
published successor of v0_25 was v0_26.

The existing regression test changed the replacement identity without also
changing `successor_binding`. It proves rejection of an inconsistent tuple but
does not cover a fully synchronized semantic rewrite.

## Required replacement closure

The successor Candidate Requirement Epoch must add production and two-Oracle
contracts for:

1. a receiver-side Release History Authority bound outside the Candidate;
2. an authenticated mapping from superseded Candidate and closure Requirement
   Epoch to the exact published successor Candidate;
3. signature, Trust Anchor, issuer Event, revision and history-tip binding;
4. Producer consumption of authoritative history rather than generation from
   Candidate closure declarations alone;
5. Factory validation against the Factory Event Store Requirement history and
   standalone validation against the receiver-pinned signed history policy;
6. a fully synchronized attack that changes replacement, successor and Receipt
   identities and recomputes all Candidate-controlled Hashes, with both Oracles
   required to fail closed;
7. preservation of v0_27 and this review evidence without runtime side effects.

The external Source Authority repair remains valid for source provenance, but
source-registry authority does not by itself establish Candidate release
history. The replacement must explicitly bind both authority domains.

