# Harness Foundry v2.9 Requirement Epoch 9 Architecture Decision Packet

Status: `PROPOSED_FOR_SINGLE_ARCHITECTURE_FREEZE_NOT_AUTHORIZATION`

Program: `PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE`

Requirement Epoch: `9`

Proposed Architecture Epoch: `1`

Proposed Control Plane Epoch: `1`

This packet is the single human-readable decision surface for the v2.9 control-plane correction. Its schemas and manifests are machine attachments, not separate human approval gates. Accepting or reading this packet does not start implementation, generate a Candidate, authorize Runtime, execute a Workpack, access the network, install, publish or certify.

## 1. Why the old architecture is superseded

Candidate v0_9 proved one deterministic Shared Control action, atomic state commit, Fencing, idempotency and crash reconciliation. It did not prove the v2.9 control plane because its core output still used a fixed three-project and 20-node v2.8 topology, defaulted automatic progress to false and encoded many node-specific authorization validators.

The old `ASM-V29-003` is therefore historical only. Requirement Epoch 9 replaces it with Profile-instantiated topology and a generic Transition Engine. Candidate v0_9 and Execution Root v0_9 remain immutable Golden Fixture evidence and have no successor execution eligibility.

## 2. Upgrade classification and reuse boundary

The upgrade class is `CONTROL_PLANE_REFACTOR_INSIDE_VERSION_UPGRADE`:

- reuse canonical JSON/Hash, SQLite Event Store, CAS, idempotency, Fencing, Spec Lock and source provenance;
- refactor fixed topology, per-node authorization, implicit Rule branching and node-specific validation paths;
- generate a replacement Candidate only after this Architecture is explicitly frozen;
- do not rewrite stable modules without a `CORR-29-*` requirement and regression obligation.

The exact component identities and dispositions are in `BASELINE_REUSE_MANIFEST.json`.

## 3. Proposed Architecture decisions

| Decision ID | Proposed decision | Why it is required |
|---|---|---|
| `ADR-V29-E9-001` | Keep the same v2.9 Program; Requirement Epoch 8→9, Architecture Epoch 0→1 and Control Plane Epoch 0→1 | Preserve authoritative history without mutating old Candidate or creating an ambiguous parallel Program |
| `ADR-V29-E9-002` | Use one append-only SQLite Event Store as the only persistent fact authority | Prevent Grant, State and Receipt stores from disagreeing |
| `ADR-V29-E9-003` | Treat Grant Ledger, State, Readback and Human Cost reports as rebuildable projections | Projections cannot create authority or repair events backward |
| `ADR-V29-E9-004` | Instantiate Program Graph from a frozen static Assurance Profile | Remove universal Main/Lab/Linkage topology while avoiding a v3.0 dynamic optimizer |
| `ADR-V29-E9-005` | Execute all node kinds through one Generic Transition Engine | Replace incident-specific `_authorized_*` control paths with data-bound contracts |
| `ADR-V29-E9-006` | Bind Decision Policy, Rule language, Evaluator, precedence, conflict and unknown behavior by Hash | Prevent logic from remaining implicit in Python branches or model prompts |
| `ADR-V29-E9-007` | Human approves a Parent Risk Envelope; the machine derives bounded Attempt Grants | Remove per-node human authorization without weakening exact byte and state binding |
| `ADR-V29-E9-008` | Implement only explicit Minimum Requirement Completion and direct invalidation in v2.9 | Prevent Workpack PASS false closure without importing the v3.0 evidence platform |
| `ADR-V29-E9-009` | Determine independence from Control Domain facts, not CLI or project count | Same Chat, model, credentials, signer or Validator cannot masquerade as independent certification |
| `ADR-V29-E9-010` | Enforce machine-counted Human Cost acceptance | Make “less human review” a release property rather than a subjective claim |
| `ADR-V29-E9-011` | Bind old v0.9 evidence through `harness-resource://baseline/v0_9` | Separate logical historical identity from current machine paths and the new Execution root |
| `ADR-V29-E9-012` | Keep automatic semantic decomposition, Evidence Reverse Index, Readiness Matrix and Coverage Delta in v3.0 | Preserve v2.9 purpose and delivery boundary |

## 4. Static Assurance Profile for this correction

Profile ID: `V29_CONTROL_PLANE_CORRECTION_AUTHORING`

| Dimension | Frozen proposal |
|---|---|
| Current external effect | None; authoring files and local synthetic fixtures only |
| Future trust impact | High; the control plane will later decide authorization and execution |
| Network and Secret | Denied during Architecture Authoring |
| Reversibility | New Epoch files are reversible; v0.9 roots are immutable |
| Semantic uncertainty | Medium until Architecture Freeze |
| Authoring assurance | `COORDINATED_SEPARATION`; no independent certification claim in this Chat |
| Future high-risk claim assurance | `INDEPENDENT_INTERNAL_CERTIFICATION` using an independent top-level task, workspace/state, credential/signer and Validator implementation |
| Human attention budget | One Architecture Freeze, one later Parent Risk Authorization, zero manual child Hash input and zero internal-flow human gates |

This is a static v2.9 Profile. It does not learn, optimize topology or add projects automatically.

## 5. Generic Transition and Rule boundary

The Transition Contract must bind inputs, allowed read/write logical roots, command, result schema, evidence obligations, retry/checkpoint policy and next-transition selection. Normative decisions additionally bind:

```text
decision_policy_ref and sha256
rule_language_id and version
rule_evaluator_ref and sha256
declared_input_schema_ref
success, failure, invalidation and next-transition rule IDs
precedence table
conflict policy
unknown policy
decision receipt schema
```

The authority order is:

```text
Platform Safety and System Authority
> Frozen Charter
> Frozen Requirement
> Architecture and Decision Policy
> Transition-local Rule
```

Unresolved conflicts return `POLICY_CONFLICT`. Missing or unevaluable inputs return `POLICY_UNKNOWN`. Both stop fail-closed. A Semantic Decision Slot may propose an interpretation but cannot directly change authoritative State.

## 6. Parent and Derived Grant invariants

A Derived Grant is legal only when the Parent is active, unexpired and unrevoked; the child expiry does not exceed the Parent; every write root, command class, permission, network/Secret/external-effect class and stop gate is equal to or narrower than the Parent; cumulative budgets remain within the Parent; Lease and Fencing are current; and the deterministic Risk Policy returns no new risk.

Parent revocation or expiry invalidates unconsumed children. `RISK_DELTA_UNKNOWN` returns to a human. Artifact Hash changes inside the same proven envelope do not create a human gate.

## 7. Minimum Requirement Completion boundary

v2.9 records only:

- explicit Requirement and mandatory Subrequirement IDs;
- Applicability decision;
- required Workpack, Case, Evidence and Oracle references;
- direct invalidation dependencies;
- `ALL_OF` completion and blocking Finding state.

It does not implement automatic semantic decomposition, a standalone Evidence Reverse Index, Readiness Matrix or Coverage Delta optimizer.

## 8. Human Cost acceptance

Historical v0.9 evidence proves at least three authority decisions, one manual Hash-bearing freeze confirmation, at least five manual operational interruptions, no derived Grants and no automatic transition. The exact bounded evidence and limitations are in `HUMAN_COST_BASELINE.json`.

The corrected vertical scenario must show:

- exactly one Architecture Freeze;
- exactly one later Parent Risk Authorization;
- zero manual child Hash input;
- at least three different node kinds auto-advanced by one Engine;
- one bounded safe retry or resume without a human gate;
- no human gate for Phase, Workpack, internal Review, Artifact Hash update or Evidence collection;
- stop only at a real Risk Delta, declared Stop Gate or unknown side effect.

## 9. Implementation slices after Freeze

1. **Generic Control Kernel**: Event/Grant models, deterministic Decision Policy, Transition Contract and Engine, projection rebuild and v2.8 Adapter.
2. **Minimum Requirement Completion**: explicit Applicability, direct evidence binding and invalidation.
3. **Profile-driven vertical fixture**: read-only validation, internal state commit and one bounded reversible Fixture action through the same Engine.
4. **Replacement Candidate authoring**: compile and validate v0.10, then stop at Candidate Readback.

No implementation slice may start before a later exact Requirement/Architecture Freeze confirmation.

## 10. Freeze scope and non-goals

The proposed Freeze would approve only the decisions and boundaries in this packet plus `CORR-29-001` through `CORR-29-008`. It would not approve:

- old or new Driver start;
- Workpack execution;
- `CONTROL_PLANE_REGISTRATION` from v0.9;
- network, Secret or external service access;
- installation, publication, certification or real target modification;
- reuse of a consumed or revoked Grant;
- any v3.0 adaptive, cross-Program, federated or learning capability.

## 11. Proposed Readback result

If the Factory Requirement IR, source snapshots, correction registry, output root and this packet are internally consistent, the next authoring state may become `REQUIREMENTS_READBACK_READY`. A later user request is still required to create a Freeze challenge, and a still later message containing the exact confirmation token is required to confirm it.
