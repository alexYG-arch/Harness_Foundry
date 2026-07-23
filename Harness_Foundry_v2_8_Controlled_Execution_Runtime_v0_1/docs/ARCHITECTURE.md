# Controlled Runtime architecture

The runtime has four boundaries:

1. The immutable candidate and Factory handoff are read-only inputs.
2. SQLite is the authoritative event and state boundary.
3. Resolved Command Manifests are runtime overlays bound by exact A3
   authorization Hashes.
4. Evidence, ledgers, and JSON state are derived or Hash-indexed outputs.

`plan-next`, `status`, `verify-run`, and `migration-plan` open SQLite read-only.
Mutation commands use `BEGIN IMMEDIATE`, revision CAS, a global Active Attempt,
and monotonically increasing fencing tokens.

Bootstrap approval is compressed only at the UI review boundary. The bundle
contains five child authorization documents with independent Hashes. The
Runtime records consumption separately. No bootstrap child carries Workpack
execution scope.

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
roots. Every command gets a unique receipt. Promotion requires successful
postflight and an explicitly independent review command.

Reservation is persisted before side effects. A receipt is persisted after
each command. On resume, a successful receipt is not repeated; a started
non-idempotent command without a receipt is outcome-unknown and cannot be
automated.

Migration never mutates the old trees. It binds their whole-tree Hashes, starts
a new epoch with no authorization and no completed nodes, and retains legacy
classification only as migration metadata.
