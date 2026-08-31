# Harness Foundry v2.9 Upgrade Start

Status: `ISOLATED_BASELINE_READY_FOR_AUTHORING`

This repository is a new, independent v2.9 upgrade project created from a tested v2.8 Chat Factory source snapshot. It does not reuse the v2.8 repository's Git directory, `runs/`, SQLite state, staging directories, temporary executors, authorization receipts, or generated candidates.

## What is reused

- The committed v2.8 Factory architecture and Git history at the locked source commit.
- Five explicitly imported, tested worktree files listed in `V2_9_UPGRADE_MANIFEST.json`.
- The v2.8 compiler, event store, CAS state, source binding, freeze, generation, validation, and Authoring Stop behavior as compatibility baseline.
- The hash-locked v2.8 Start Package as read-only normative input.

## What is not reused as authority

- Any previous Program ID, `factory.sqlite3`, Grant, Signer, runtime receipt, Candidate Lock, Release Lock, or Certificate.
- Any `.codex_stage*`, temporary recovery directory, cache, installed package, or external execution root.
- Any v2.8 PASS as evidence that a v2.9 requirement has been implemented.

## Active target

The active v2.9 proposal is `docs/HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN.md`. The implementation target is its P0-01 through P0-10 minimum trustworthy execution loop. Advanced v3.0 abilities are informative future inputs and cannot block v2.9.

The first authoritative authoring Program is:

```text
PROGRAM-HARNESS-FOUNDRY-V2-9-UPGRADE
```

It must remain in Authoring-only states until the user reviews the Requirement Readback and, in a later message, supplies the exact Factory freeze confirmation token. Generated Workpacks and Program Driver execution are out of scope for this start step.

## Upgrade shape

This is a source-level upgrade with a controlled package/state reconstruction:

- tested v2.8 Factory modules are the reused implementation baseline;
- v2.9 uses a new repository, Program, SQLite state, output root and generated Start Package;
- the Start Package reorganizes how the reused code is changed and verified; it does not require rewriting unchanged v2.8 modules;
- old v2.8 runtime state and the epoch-0 v2.9 Candidate are historical evidence, not migration input.

Portable artifacts persist only repository-relative references or declared logical Resource URIs. Absolute paths resolved on the current machine are local runtime bindings; they may exist in the private Program state for resumption but must not be copied into Candidate, Frozen Requirement IR, manifests, README or release archives.

## Verify the imported baseline

```bash
python3 tools/hffactory.py verify-spec --json
python3 tools/validate_skill.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Current sequence

```text
Isolated repository
→ Tested v2.8 source snapshot import
→ New v2.9 Program and source registration
→ Requirement Readback
→ explicit later Freeze confirmation
→ v2.9 implementation Workpacks
→ independent runtime evidence
```

Current non-claim: no v2.9 code capability, Start Package Candidate, Workpack execution, runtime, migration, release, or certification is complete merely because this repository exists.
