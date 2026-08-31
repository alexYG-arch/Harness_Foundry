# Harness Foundry v2.9 v0_24 Human Review

## Review boundary

- Candidate: `Harness_Foundry_v2_9_Start_Package_Candidate_v0_24`
- Review mode: read-only Human Review; Human Gate was not approved.
- Execution Root v0_24 was not created.
- Driver, Workpack, runtime authorization and release commit were not started.
- Candidate v0_24 and its original validation artifacts remain immutable historical evidence.

## Release-blocking findings

### HR-V024-001 — Epoch 23 requirements were not routed into the release producer

The frozen Requirement IR required actual Artifact-byte resolution, a receiver-side
Trust Anchor and independent Authority Normalization Oracles. The v0_24 producer
still emitted the earlier release adapter and contracts, so the declared remediation
did not become production behavior.

Required closure: the Producer must select the Epoch 24 remediation explicitly and
emit the new adapter, contracts, schema, manifest requirements and Human Review
closure material from that same requirement branch. Omitting the route must fail
Candidate validation.

### HR-V024-002 — release commit still trusted matching Hash claims instead of Artifact bytes

The v0_24 adapter compared the four Hash values asserted by Event Store state with
the same values in a signed authorization. If both sources carried the same wrong
values, the comparison could pass because Candidate content, frozen Requirement IR,
Executor release and Human Gate receipt bytes were not resolved and re-hashed by the
receiver during the release transaction.

Required closure: a Hash-bound receiver resolver must open the exact four artifacts,
reject symlinks and path substitution, compute their hashes inside the authoritative
`BEGIN IMMEDIATE` transaction, compare the results with both State and Authorization,
and commit the computed values. A fake resolver or a synchronized wrong-Hash pair
must fail closed.

### HR-V024-003 — the Candidate could replace its own Trust Anchor

The v0_24 production path loaded `AUTHORITY_TRUST_ROOT.json` from inside the
Candidate. An attacker able to replace the Candidate could replace the public key,
contract and signatures together, then recompute local Hashes.

Required closure: production authority verification must receive an independently
provisioned receiver-side Trust Anchor. Candidate-packaged authority metadata is
non-authoritative distribution information only. Missing, malformed or Candidate-
local anchors must fail closed without an interactive fallback.

### HR-V024-004 — both Authority Normalization checks shared Candidate-local truth

The standalone self-check and Factory Validator both accepted Candidate-contained
declarations as their expected truth. A synchronized rewrite of Frozen Requirement
IR, Source Manifest and dependent Hashes could therefore move both checks together.

Required closure: the Factory Oracle must compare against its persisted SQLite
Requirement IR and Source Registry supplied from outside the Candidate. The
standalone Oracle must compare against a receiver-supplied Source Authority Policy
Lock located outside the Candidate. The two Oracles must use separate implementations
and reject a missing external policy, a relabeled authority and all synchronized
downstream re-hashing.

## Required adversarial coverage

- omit the Epoch 24 Producer or Validator route;
- omit the receiver-side Source Authority Policy Lock;
- synchronize wrong Artifact Hashes across Event Store and a validly signed Authorization;
- supply a fake Artifact-byte resolver that returns matching claims;
- replace the Candidate-local Trust Anchor and sign with the matching attacker key;
- synchronize Authority relabeling across Frozen Requirement IR, Source Manifest and downstream Hashes;
- substitute a symlink or change Artifact bytes before commit.

Each case must execute a real mutation or production call. A hard-coded PASS/FAIL
case name is not evidence. Factory and standalone Oracles must reject their applicable
attacks without calling each other or sharing Candidate-local authority.

## Replacement and non-claims

The successor Candidate version is not bound by this review. A later exact human
root-binding answer, Requirement Readback and human-confirmed Requirement Freeze are
required before any replacement Candidate may be created. This review does not
create a Candidate or Execution Root, approve or consume a Human Gate, grant runtime
authority, execute a transition, start a Driver or Workpack, install, publish,
release or certify v2.9.
