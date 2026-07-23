# Controlled Runtime architecture

The runtime has four boundaries:

1. The immutable candidate and Factory handoff are read-only inputs.
2. SQLite is the authoritative event and state boundary.
3. A generic Resolver expands one provider profile into ordered per-Workpack
   Command Manifests. The immutable overlays are first registered without
   execution authority, then bound by exact A3 authorization Hashes.
4. Evidence, ledgers, and JSON state are derived or Hash-indexed outputs.

`plan-next`, `status`, `verify-run`, and `migration-plan` open SQLite read-only.
Mutation commands use `BEGIN IMMEDIATE`, revision CAS, a global Active Attempt,
and monotonically increasing fencing tokens.

Bootstrap approval is compressed only at the UI review boundary. The bundle
contains five child authorization documents with independent Hashes. The
Runtime records consumption separately. No bootstrap child carries Workpack
execution scope.

Driver materialization vendors the standard-library Runtime into the execution
root. Runtime verification launches that vendored Driver in isolated Python
mode, removes `PYTHONPATH`/`PYTHONHOME`, performs a read-only state readback,
and only then closes `PROGRAM_DRIVER_RUNTIME_VERIFIED`.

`resolve-overlays` binds a resolver input to the current
Program/epoch/candidate, expands the selected nodes in declared Workpack order,
computes executable content Hashes, validates the same runtime contract as
execution, and delegates immutable registration. `register-overlays` remains
the boundary for external resolvers. Neither command creates authorization or
runs commands. `authorization-plan` rejects any manifest that does not exactly
match the currently registered binding.

A3 scope is an intersection:

```text
candidate Automation Profile
∩ active authorization project/epoch/candidate bindings
∩ authorized DAG nodes and Workpacks
∩ Command Manifest Hash
∩ allowed write roots
∩ environment IDs
∩ expiry
∩ transition, loop, and wall-time budgets
```

A command is launched only with `shell=False`, an absolute executable whose
final content Hash is verified, an absolute bounded cwd, and declared write
roots. Every command gets a unique receipt bound to its Workpack. A node with
multiple Workpacks cannot be promoted as one opaque unit: each Workpack must
complete execute, postflight, independent review, Evidence Hash, and promotion
in declared order.

Review commands have a distinct executor identity, `READ_ONLY` target mode,
and no declared write roots. The runtime persists a pre-review target
fingerprint and rejects any actual mutation, including after crash/resume.
Acceptance failure writes an immutable Finding. Bounded fix commands receive
the exact Finding path and Hash through mandatory tokens, then postflight and
review run again before promotion.

Reservation is persisted before side effects. A receipt is persisted after
each command. On resume, a successful receipt is not repeated; a started
non-idempotent command without a receipt is outcome-unknown and cannot be
automated.

Migration never mutates the old trees. It binds their whole-tree Hashes, starts
a new epoch with no authorization and no completed nodes, and retains legacy
classification only as migration metadata.
