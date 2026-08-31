# v2.9 Code Reuse and Change Map

Status: `REQUIREMENT_EPOCH9_ARCHITECTURE_PROPOSAL_NOT_FROZEN`

The exact current module identities, v0.9 historical evidence bindings, dispositions and regression obligations are machine-recorded in `docs/v2_9_epoch9/BASELINE_REUSE_MANIFEST.json`. This narrative map is explanatory; the manifest is the proposed Architecture Freeze attachment.

v2.9 is not a rewrite from an empty repository. It imports the tested v2.8 code and changes only the components required by P0-01 through P0-10. Existing behavior remains the compatibility baseline until a v2.9 test explicitly changes it.

| v2.8 component | v2.9 disposition | Planned v2.9 responsibility |
|---|---|---|
| `store.py` | Reuse and extend | Preserve SQLite Event Store, CAS, idempotency and event chain; add v2.9 authoring/runtime event types without reusing old Program state |
| `models.py` | Extend | Add Requirement Lock, Architecture Lock, applicability, Policy disposition, human-decision schemas and portable logical Root/Resource references |
| `service.py` | Extend behind existing states | Add authoring `advance-until-gate`, risk-delta decisions and machine-derived attempt/phase grants while preserving freeze confirmation |
| `compiler.py` | Extend production-first | Compile Architecture, Policy, enforcement, evidence applicability and portable manifests; persist logical references instead of resolved local paths and do not solve producer gaps by Validator-only changes |
| `validator.py` | Split responsibilities | Preserve structural validation; add claim/applicability and local-binding rejection checks, without becoming the producer or accepting a path merely because it exists on the author machine |
| `traceability.py` | Extend | Trace Requirement → Architecture → Policy/Run → Evidence/Receipt and dependency invalidation |
| `spec_lock.py` | Reuse and version | Keep exact v2.8 normative input binding; add v2.9 extension/release identity without changing the v2.8 package |
| `cli.py` | Extend, keep compact | Add combined authoring/runtime commands instead of many one-check CLI stops |
| repo-local Skill | Revise later | Teach v2.9 readback and auto-progression while retaining exact freeze-token and Authoring Stop rules |
| existing 78 tests | Keep as regression floor | Every v2.9 change must keep or explicitly supersede the verified v2.8 behavior |

## Reuse rule

```text
Reuse deterministic state, hashing, isolation, freeze and publication mechanics.
Extend requirement, architecture, policy, authorization and auto-progression semantics.
Replace only behavior proven incompatible with a frozen v2.9 P0 requirement.
Never import v2.8 runtime state as v2.9 evidence.
```

## Path migration rule

v2.8 currently resolves and persists absolute `candidate_root`, `execution_root`, command `cwd` and executable paths. v2.9 reuses the boundary checks but changes the persisted contract:

```text
persist logical root/ref
→ resolve against explicitly supplied local roots at runtime
→ check containment after resolution
→ execute
→ never write the resolved absolute value into a shareable artifact
```

The local Program database may retain machine bindings for resumption, but it is `LOCAL_ONLY_NON_EXPORTABLE`. A Candidate, Frozen Requirement IR, manifest, README or release archive containing those bindings fails P0-10.

## Upgrade versus refactor

The Start Package chain regenerates a Candidate and creates new Program state, so the package/state layer is reconstructed. That does not make the Factory source a wholesale rewrite: its tested v2.8 implementation remains the baseline and only incompatible contracts are replaced. The source-level upgrade is measured by this map and Git diff: unchanged modules are reused, modified modules must cite a P0 requirement, and new modules must prove an existing extension point cannot carry the responsibility.
