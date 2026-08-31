# Harness Foundry v2.9 v0_20 Human Review

## 1. Review verdict

- Candidate: `Harness_Foundry_v2_9_Start_Package_Candidate_v0_20`
- Candidate content SHA-256: `358bfcab7e92944a13f020594a627ca11b9ef6fcb7ec977f44e9b0c7969018b2`
- Factory state at review: `CANDIDATE_READY_FOR_HUMAN_REVIEW`
- Factory revision at review: `146`
- v0_20 Factory Validator and standalone self-check: `PASS`, but incomplete
- Runtime, Driver, Workpack, install, publication and certification: `NOT_STARTED`
- Human Review verdict: `BLOCK_HUMAN_GATE`

The exact v0_20 production Event Store Adapter can be pointed at an
attacker-created native-looking SQLite store and a matching caller-created
binding. Because both the store identity and binding Hash are self-consistent,
the old Adapter accepts the forged authority chain. The same implementation
also trusts a caller-declared Adapter Contract Hash and treats a self-declared
`RELEASE_COMMIT_AUTHORIZED` event as authority. The two green oracles therefore
prove internal consistency, not an external authorization root.

## 2. HR-V020-001: Event Store binding has no external trust root

Severity: `P0 / RELEASE_BLOCKING`

The v0_20 binding is protected only by a Hash calculated from the binding
itself. An attacker who can create a database can also calculate:

- a matching database identity;
- a matching Adapter binding;
- a valid binding Hash;
- a complete internally consistent event Hash chain.

This is comparable to printing an employee card and signing it with the same
printer: the card is internally neat, but no company authority has vouched for
it. The replacement must carry only a pinned external public verification root
and require an Ed25519-signed authority-binding receipt over the exact Program,
scope, instance, Requirement Epoch, database identity, logical database URI,
Adapter implementation Hash, entrypoint Hash and actual Contract Hash. The
private signing key must not be packaged in the Candidate.

## 3. HR-V020-002: RELEASE_COMMIT_AUTHORIZED is self-declared and replayable

Severity: `P0 / RELEASE_BLOCKING`

In v0_20, an event named `RELEASE_COMMIT_AUTHORIZED` is treated as authority
because of its event type and payload fields. The same Event Store writer that
wants to commit can therefore write its own permission. The authorization also
has no one-shot consumption record, lease, fencing token or idempotency binding,
so a previously accepted event can be reused.

The replacement must require a signed, time-bounded, one-shot authorization
that binds the evaluated Event Store tip, control state, exact proposal
decision, Candidate/Requirement/Executor/Human-Gate identities, lease,
idempotency key and monotonic fencing token. The atomic commit must consume the
authorization before committing `RELEASE_READY`, and reject replay or fencing
regression.

## 4. HR-V020-003: actual Adapter Contract Hash is not bound

Severity: `P0 / RELEASE_BLOCKING`

v0_20 checks whether the binding contains a syntactically valid
`adapter_contract_sha256`; it does not recompute the exact packaged
`EVENT_STORE_AUTHORITY_ADAPTER_CONTRACT.json`. A caller can therefore place an
arbitrary 64-character Hash in both the forged binding and forged authority
story without changing the actual Contract artifact.

The replacement must resolve the Contract from the Adapter's own Candidate
root, verify the Contract's self Hash, and require the externally signed binding
to equal that recomputed Hash. A caller path or caller-supplied Contract object
is not an authority input.

## 5. HR-V020-004: both green oracles share the same blind spot

Severity: `P0 / RELEASE_BLOCKING`

The v0_20 standalone self-check and Factory Validator validate many fields and
Hashes, but neither executes the exact production attack: production Adapter,
attacker-created store, matching self-consistent binding. They agree because
both model the same incomplete rule.

The replacement requires two different checks:

1. standalone self-check imports the exact packaged production Adapter and
   proves that a forged native store plus matching attacker-signed binding is
   rejected;
2. Factory Validator independently reconstructs and verifies the external
   signature rule without importing the Candidate production Adapter.

The Factory oracle must also fail if it starts importing or reusing the
Candidate Adapter implementation, because copied code is not independent.

## 6. Reproduced evidence

- Exact v0_20 attack harness SHA-256:
  `ddd1fd1338747a825a1f26a292d816916778891df7263f52a76bd8c37dbdd18f`
- Observed v0_20 result: `FORGED_AUTHORITY_CHAIN_ACCEPTED`
- Wrong actual Contract Hash: accepted by v0_20
- Self-declared `RELEASE_COMMIT_AUTHORIZED`: accepted through
  `RELEASE_READY_COMMITTED` by v0_20
- Required replacement result for all cases: fail closed before an authority
  value crosses the Adapter or a release event is committed

This report records the Human Review result. It does not grant an authority,
approve a Human Gate, or claim Runtime execution.

## 7. Replacement acceptance set

The replacement Candidate must independently reject at least:

1. unsigned matching Event Store binding;
2. forged Event Store plus matching binding signed by an attacker key;
3. binding whose Hash is valid but whose actual Adapter Contract Hash differs;
4. self-declared or attacker-signed release commit authorization;
5. replay of a previously consumed signed release commit authorization;
6. stale evaluated tip followed by a different live authorization or commit;
7. a self-check or Factory oracle weakened while all related file Hashes are
   recomputed.

## 8. Preserved state and non-claims

- Candidate v0_20 and its existing Human Review/adversarial evidence remain
  unchanged and read-only.
- No v0_21 Execution Root is created by remediation authoring.
- No Human Gate is consumed.
- No Driver, Workpack or transition is started.
- No Parent Risk Envelope, Derived Grant, registration authorization or release
  authorization is granted.
- No install, publication, migration, Runtime PASS or certification is claimed.

