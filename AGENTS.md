# Harness Foundry Chat Factory guidance

- Treat the sibling `Harness_Foundry_v2_8_Start_Package` as read-only normative input.
- For requests to create, revise, resume, or inspect a v2.8 Start Package, use the repo-local `harness-foundry-start-author` skill.
- Use the Factory CLI and persisted `program_id`; do not keep authoritative state only in chat.
- Do not directly edit SQLite state, generated candidate files, or immutable source snapshots.
- Never submit a freeze `confirmation_token` unless a later user message contains it exactly.
- Never pass a replacement `--spec-root`, generation `target_root`, or generation `staging_root`.
- Preserve each Program's independent `runs/<program_id>/factory.sqlite3`; JSON/JSONL views are derived, not authoritative.
- Do not execute generated Workpacks, start a Program Driver, install target tools, or claim Harness/Conformance completion.
- A successful candidate must contain no `.template.*`, unresolved placeholder, fake Hash, `PLANNED-REF`, granted authorization, active Workpack, or started Driver.
- Run `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v` after implementation changes.
- Run `python3 tools/hffactory.py verify-spec --json` and validate the repo Skill after workflow changes.
