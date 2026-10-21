# Program Charter: <target-name>

## 0. Metadata

- Charter ID: `<ID>`
- Version: `0.1.0-draft`
- Status: `DRAFT`
- Owner: `<OWNER>`
- Human Approver: `<APPROVER>`
- Selected Profile: `<FULL|STANDARD|LITE>`
- Source Manifest: `canonical_sources/SOURCE_MANIFEST.json`
- Normative Atom Catalog: `canonical_sources/NORMATIVE_ATOM_CATALOG.json`

## 1. Mission

### Problem

<Why this Agent or Harness must exist.>

### Intended Outcomes

| Outcome ID | Observable result | Public entry | Evidence | Owner | Capability level |
|---|---|---|---|---|---|
| `<PO-ID>` | `<RESULT>` | `<ENTRY>` | `<EVIDENCE>` | `<OWNER>` | `<LEVEL>` |

### Failure Signals

- <False-success condition that must block.>

## 2. Scope

### In Scope

- <...>

### Out of Scope

- <...>

### Non-goals

- <...>

### User Adjustments

| Adjustment ID | Original rule/source | Adjustment | Reason | Authority | Downstream impact |
|---|---|---|---|---|---|
| `<ADJ-ID>` | `<SOURCE>` | `<CHANGE>` | `<WHY>` | `<WHO>` | `<IMPACT>` |

## 3. Build System and Run System

- Build Program Driver: `<BUILD-ENTRY>`
- Final Installed Runtime Entry: `<RUNTIME-ENTRY>`
- Boundary: Build Program construction evidence cannot be used as runtime execution evidence.

## 4. Authority Model

<Canonical locations, writers, reviewers and promotion authorities.>

## 5. Runtime Ownership

<Stage → primary runtime → artifact authority → trusted attestation → missing-runtime behavior.>

## 6. Phase and Gate Policy

`PHASE_DEPENDENCY_MANIFEST.json` is authoritative. P4 requires the current P3 lock or approved P3 N/A lock plus C3 PASS.

## 7. Conformance and Release

Release-ready requires installed artifact evidence, Pack B1, Linkage D, external C4 Certificate and a Certified Release Lock.

## 8. Risks and Open Decisions

- `<DECISION-ID>: <QUESTION>`

## 9. Approval

This draft does not authorize Coding until the Charter, Profile and G0 Start Gate are approved.
