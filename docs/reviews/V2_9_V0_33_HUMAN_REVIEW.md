# Harness Foundry v2.9 v0_33 Human Review

## Review decision

`FAIL — REOPEN_REQUIRED`

This Human Review was read-only against the published v0_33 Candidate. It did
not approve or consume a Human Gate, create an Execution Root, start a Driver or
Workpack, grant runtime authority, or execute a runtime transition. The v0_33
Candidate remains immutable historical evidence.

## Reviewed identity

- Program: `PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE`
- Candidate: `v0_33`
- Candidate Requirement Epoch: `33`
- Candidate Requirement IR SHA-256:
  `02e2981b17a67e6c229497370ef8a75fe3ba9dff7781e72b06a502f9b8e34bea`
- Candidate Generated validation-basis revision: `256`
- Candidate Generated validation-basis tip SHA-256:
  `64b60af613822dee79d5b46ba871a5c0749d72dbcac836838a5ad28e538b05b6`
- Candidate Validation Report SHA-256:
  `0ec9fcd5b9d9d965eb2ce724588e77b5e666ee4c82d7b2f2e344b2564765b14c`
- Candidate Validation Report Receipt SHA-256:
  `d31d2e8b9a517d86d4687d49893d7d712ac8cd39336b88b59f1aec9b10ca3d9e`
- Human Review input Factory revision: `257`
- Human Review input Factory state SHA-256:
  `3418c330fc610bae027863c2a6feb87358fb395ff3866d9c97e2730f34b13549`

## Blocking findings

### HR-V033-001 — Existing Execution Root boundary is ambiguous

The official Runtime Binder did not define a sufficiently strict boundary for
an already-existing `execution_root`. A normal bind could risk treating an
existing directory as reusable state. The default must instead reject every
existing root before any write. Idempotent re-entry is a separate, explicit
operation and is valid only when the existing immutable binding receipt exactly
matches the newly recomputed Candidate, inventory, dependency, authority and
binding result. The Binder must never overwrite that receipt.

### HR-V033-002 — Closure could claim regressions without executing them

The frozen Requirement could name `required_regression_tests`, while Closure
and Factory validation relied on declarations and source-file Hashes. A test
name in a JSON object and a Hash-bound test file prove only that text exists;
they do not prove that the named test function exists exactly once or that it
ran successfully. The Factory Validator must resolve the exact test module,
parse its definitions, execute every frozen test selector, and bind the result
in a detached Candidate receipt and Validation Report.

## Required replacement closure

The v0_34 replacement must:

1. reject any existing Execution Root by default before the first write;
2. allow re-entry only with an explicit flag and an exact, immutable prior
   runtime-binding receipt; never repair or overwrite a mismatching receipt;
3. exercise real official-Binder attacks for dangling Candidate Resource URIs,
   portable inventory gaps, missing runtime dependencies, failure leaving a
   fresh root absent, and existing-root/re-entry behavior;
4. make Factory Validator verify that every frozen required test exists exactly
   once in the Hash-bound implementation and executes successfully;
5. generate a detached Factory regression execution receipt and include its
   execution metadata in the Candidate Validation Report;
6. make Closure bind that execution receipt rather than inferring PASS from
   declarations or implementation file Hashes;
7. route the Epoch 34 Requirement through Producer, Factory Validator and
   standalone self-check while preserving all earlier release-closure rules;
8. preserve v0_33 and this review evidence without runtime side effects.

## Implemented remediation evidence

- Compiler SHA-256:
  `d53c092f1bf37481b964847ab9ac684f743f6d7dee602d7b9636ad959139694a`
- Factory Validator SHA-256:
  `d2db16566b0f43fca40feac47cf83509456c8a5285f3444f48e05a4820d943c0`
- Release-closure regression test SHA-256:
  `a365b1c6a0ce0f56fd39d63d748d2a1fd418e5568945f68b2f982eeacb9956fb`
- Full Factory suite:
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`
- Full Factory result: `PASS — 177/177`
- v2.8 Spec Lock: `PASS — 101 files`
- v2.8 Spec content SHA-256:
  `be81e6b46573abcbff0a9851812b3b2bb78814928e57a59d65a2b5bb733b8503`
- Factory skill validation: `PASS`
- `git diff --check`: `PASS`

These results establish authoring implementation readiness only. They do not
freeze Epoch 34, create or approve v0_34, bind an Execution Root, or prove a
runtime transition.
