# Target Profile: <target-name>

## Classification

- Target Type: `<AGENT|HARNESS|HYBRID>`
- Selected Governance Profile: `<FULL|STANDARD|LITE>`
- Risk Level: `<LEVEL>`
- Runtime Form: `<LOCAL|SERVICE|CONTAINER|DESKTOP|OTHER>`
- Release Form: `<WHEEL|BINARY|CONTAINER|BUNDLE|OTHER>`

## Runtime Inventory

| Runtime ID | Role | Artifact authority | Deployment location | Missing behavior |
|---|---|---|---|---|
| `<RUNTIME-ID>` | `<ROLE>` | `<ARTIFACT>` | `<LOCATION>` | `<GATE-STOP>` |

## Stage and Tool Topology

<Stages, orchestration, external tools, data flow and human gates.>

## Data, Network and Permission Boundary

<Data classes, secrets, network allowlist, write boundaries and audit requirements.>

## Build and Install Boundary

- Build Program entrypoint: `<BUILD-ENTRY>`
- Final installed runtime entrypoint: `<RUNTIME-ENTRY>`
- Editable/source-tree execution accepted for certification: `false`

Unknown fields remain `UNKNOWN_REQUIRES_DECISION`; they must not be filled with invented facts.
