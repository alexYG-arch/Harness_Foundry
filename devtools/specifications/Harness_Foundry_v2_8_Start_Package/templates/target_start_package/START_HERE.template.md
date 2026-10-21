# START HERE: <target-name>

## Current State

```text
authoring_activity = BUILD_PROGRAM_AUTHORING
execution_mode = AUTHORING_ONLY
current_state = <START_PACKAGE_DRAFT_AUTHORING_CANDIDATE|START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW>
execution_started = false
install_started = false
certification_started = false
controlled_auto_progress_ready = false
```

## Read First

1. `README.md`
2. `PROGRAM_CHARTER.md`
3. `TARGET_PROFILE.md`
4. `canonical_sources/SOURCE_MANIFEST.json`
5. `canonical_sources/NORMATIVE_ATOM_CATALOG.json`
6. `AUTHORING_HANDOFF.md`
7. `THREE_PROJECT_PROGRAM_MANIFEST.json`
8. `PROGRAM_AUTOMATION_POLICY.json`

## Open Decisions

Read `START_CONTEXT.json.unresolved_human_decisions`. A blocking decision must be closed before the Gate it names.

## First Future Action

Review and approve the Profile, Charter and Start Package validation report. Do not activate the first Workpack from this document.

## Future Driver Entry

After approval, use the dedicated Program Driver entrypoint and an explicit `EXECUTION_AUTHORIZATION`; never treat this document as an executable dispatcher. Real target install remains a separate hard authorization.
