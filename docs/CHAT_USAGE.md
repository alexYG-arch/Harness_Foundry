# Codex Chat usage

Codex must select one route before acting. Natural language is the user interface; the repository CLI is the engineering interface.

## Before any Harness build: show the document and wait

Every input type follows [the upstream build-document policy](GENERIC_BUILD_PLAN.md):
clarify through Q&A, save and show a versioned build document, then wait for
the user's explicit review and confirmation before entering Foundry. No open
questions or internal PASS does not skip document delivery. An answer to a
clarifying question, an agent review, a delegated grant or an old approval does
not confirm the final document. Create no Program, Candidate or target directory
before that decision. Core checks, Foundry source engineering and read-only
history inspection are unaffected.

The public build and compatibility authoring entrypoints check a host-recorded
review and the unchanged full document. Historical state alone is not sufficient.
The trusted host authenticates actual human messages and checks semantic scope. Material changes to
the document's contract require renewed review; implementation details do not.
After document confirmation and separate runtime authority, work continues within
scope without per-Workpack approval.

## DEFAULT_ROUTE_FOUNDRY_CORE

This is the default route. It operates and validates the local 41-capability Harness Foundry product without creating a Factory Program or building a target Harness.

```bash
python3 tools/hffactory.py version --json
python3 tools/hffactory.py validate-core --json
python3 tools/hffactory.py project-core-evidence --json
python3 tools/hffactory.py package-local --json
```

Consecutive implementation, focused regression, core validation, evidence projection, and temporary relocation smoke are one engineering flow. They do not need per-step Human Review or generic “继续” prompts. A failing implementation or test is a repair signal, not a new governance ceremony.

This route must not create a Program, Candidate, Execution Root, Runtime Bind, Driver, Workpack, or A3. It must not run dynamic adversarial reproduction, optional security hardening, external certification, installation, or publication.

## EXPLICIT_ROUTE_GENERIC_BUILD

After the upstream document confirmation, an explicit generic build or scoped
acceptance case uses [the Build CLI](GENERIC_BUILD_CLI.md). Prepare and display
the concrete execution scope, record the real user's decision, then advance
within that scope. Document confirmation alone is not execution permission.

## OPTIONAL_ROUTE_START_PACKAGE_COMPATIBILITY

Enter authoring only when the user explicitly requests a Start Package Candidate or continuation of an existing Factory `program_id`, and the upstream build document has been confirmed. Naming a Program permits inspection, not automatic advancement. The Factory CLI and SQLite-backed Program remain authoritative; Chat history does not.

1. Verify the pinned specification and create or resume the Program.
2. Register sources and apply the requested Requirement mutation.
3. After each mutation, run:

   ```bash
   python3 tools/hffactory.py advance-authoring-until-gate --program-id PROGRAM_ID --json
   ```

4. The bounded advance performs internal classification, charter-clause disposition, policy coverage, Architecture Candidate, Run Contract, evidence applicability, and Readback progression using one state CAS. Do not ask the user to approve these deterministic internal steps.
5. If the result contains a real blocking gap, ask at most three highest-priority questions, record the answers, and invoke the bounded advance again without requesting an extra continuation message.

### TRUE_GATE_ONLY

Return to the user only for a true gate:

- missing user-owned requirement information or a blocking high conflict;
- mandatory upstream build-document Human Review, including after internal PASS;
- changed external state or stale bindings that cannot be refreshed read-only;
- exact Requirement Freeze or Architecture Lock confirmation;
- authority expansion, irreversible effects, or unknown side effects;
- an explicitly selected Candidate Human Review.

Never auto-confirm a lock, consume a token not supplied in a later user message, widen scope, or cross an execution boundary.

## Freeze, generate, and stop

When the Readback is complete, the Factory may return a Hash-bound freeze challenge and exact `confirmation_token`. Codex must show it and wait. Only a later user message containing the exact token may be submitted.

Generate only after a separate exact authorization. Do not override the frozen output or staging roots. Successful optional-route generation stops at:

```text
START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
AUTHORING_STOP
```

The authoring workflow must not approve or register the Candidate, create or bind an Execution Root, execute Workpacks, start a Driver, install a target, or claim Harness/Conformance completion.

## Resume safely

For an existing `program_id`, read `status` and `readback`. Advance from the persisted SQLite state and current State Hash only when the upstream document-review policy and applicable authority are satisfied; old state is not a substitute for that review. Replaying an identical bounded-advance request is read-only/idempotent; a state conflict requires a fresh status read, not a guessed retry.
