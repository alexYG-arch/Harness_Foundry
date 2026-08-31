# Harness Foundry v2.9 v0_26 Human Review

## Review decision

`BLOCK_START_PACKAGE_HUMAN_GATE`

This was a read-only Human Review of the published v0_26 Candidate. The review
did not approve or consume a Human Gate, create an Execution Root, start a
Driver or Workpack, grant authority, or execute a runtime transition. The
Candidate directory was retained byte-for-byte as historical evidence.

## Reviewed identity

- Program: `PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE`
- Candidate: `candidate-v0_26`
- Candidate content SHA-256: `cfc092776c9089f1fe1745af2c1ef06d2b0f92045d78717917c20e6bda57ecee`
- Frozen Requirement IR SHA-256: `8556136fa9164d07814a299de89840dfef1e9c09eb7216421587884ffa344978`
- Review input Factory revision: `193`
- Review input Factory state SHA-256: `bdd7044b2bdc2ab09017c6926aae0a96abc9c1cda5205966428c6af218940595`

## Blocking findings

### HR-V026-001 — standalone did not consume PORTABLE_SOURCE_INDEX semantics

`tools/self_check.py` checked the portable file inventory, Source Manifest,
source receipts and payloads, but did not load and independently interpret
`canonical_sources/PORTABLE_SOURCE_INDEX.json`. In an isolated copy, changing
an Index `payload_ref` and then recomputing the Human Review evidence Hashes and
Portable File Manifest made the old standalone self-check return `PASS`. The
Factory Validator independently returned `PORTABLE_SOURCE_PAYLOAD_INVALID`.

This proves a common release Hash can describe tampered bytes without proving
that those bytes still mean the right thing. The replacement must make the
standalone Oracle parse the Index itself, derive every expected Resource URI,
and compare each receipt, payload, copy policy and source Hash.

### HR-V026-002 — Source Authority Policy Lock was not externally authentic

The old lock was external by path and protected by a public self-Hash, but had
no receiver-pinned public key, signature, issuer identity, issuance event,
event revision, or source-registry tip binding. A byte-identical Candidate
semantic projection copied to another external file passed the standalone
check. Moving the file outside the Candidate changed its location, not its
authority.

The replacement must require a receiver-controlled Trust Anchor and pinned
anchor Hash, verify an Ed25519 signature, and bind the signed policy to the
issuer event identity, event revision, Requirement Epoch and source-registry
tip. Candidate-local keys and self-selected Candidate metadata remain
untrusted.

### HR-V026-003 — v0_25 Closure used a placeholder replacement identity

The frozen v0_25 remediation and generated Closure Receipt recorded
`candidate-v0_26-root-unbound` even though v0_26 had already been bound,
frozen, generated and reviewed. The old Oracles only compared the receipt with
the same frozen declaration, so synchronized incorrect identity passed.

The replacement must use `candidate-v0_26` and cross-check its parsed version
against `successor_binding.candidate_version`. The Closure Receipt must also
bind the current Package ID, current Candidate version and current Requirement
Epoch, so historical closure identity cannot be accepted merely because two
copies repeat the same error.

## Required replacement closure

The v0_27 Requirement Epoch must add production and two-Oracle contracts for:

1. independent standalone validation of `PORTABLE_SOURCE_INDEX`;
2. synchronized-rehash Index tampering rejected by standalone and Factory;
3. receiver-pinned signed Source Authority Policy Lock with issuer/event/tip
   freshness binding and a practical README provisioning flow;
4. exact v0_25 replacement identity plus successor, Package Identity and
   Requirement Epoch cross-checks;
5. preservation of v0_26 and this review evidence without runtime side effects.

