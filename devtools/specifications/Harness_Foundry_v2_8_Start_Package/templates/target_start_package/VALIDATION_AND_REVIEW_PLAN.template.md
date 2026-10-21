# Validation and Review Plan

| Requirement/Atom | Validation layer | Positive case | Negative case | Evidence | Authority |
|---|---|---|---|---|---|
| `<ATOM-ID>` | `<AUTHORING|CODING|RUNTIME|LINKAGE|LAB|HUMAN>` | `<CASE>` | `<CASE>` | `<EVIDENCE>` | `<OWNER>` |

## Required Separation

- Authoring structural PASS does not prove code exists.
- Coding tests do not prove installed runtime reachability.
- Linkage PASS does not prove Conformance PASS.
- Pack parser PASS is not an authoritative Lab assertion.
- External C4 and Certificate require the installed Candidate and trusted attestation.

## Mandatory False-success Coverage

Reference the target-specific implementations of all tests required by Harness Foundry v2.8 `docs/11_acceptance_and_negative_tests.md`.
