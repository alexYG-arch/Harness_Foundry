# Authority and Execution Boundary

## Authority Order

```text
Human-approved Charter and Canonical Intent Baseline
> locked source, contract and rule assets
> Phase/Workpack contracts
> implementation and receipts
> examples and generated notes
```

## Artifact Ownership

| Artifact class | Canonical path | Writer | Reviewer | Promotion authority |
|---|---|---|---|---|
| `<CLASS>` | `<PATH>` | `<WRITER>` | `<REVIEWER>` | `<AUTHORITY>` |

## Execution Boundary

- Current authoring may write only the target Start Package.
- Generated commands are `DECLARE_ONLY`.
- Build Program registration uses `auto_start=false`.
- Workpack execution, package build, installability, certification install, Lab certification and real target install require separate modes.
- Build Program Driver and Final Harness Runtime are distinct absolute entrypoints.
- Self-reported Runtime receipt is not trusted attestation.

## Side-effect Boundary

<Allowed roots, forbidden roots, network, process, service, package and external-resource policy.>
