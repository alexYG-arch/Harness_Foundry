# Factory Chat contract

Run all commands from the Factory repository root. Request files must be absolute paths. Each mutating call emits exactly one JSON object on stdout.

This contract belongs to `OPTIONAL_ROUTE_START_PACKAGE_COMPATIBILITY`. `DEFAULT_ROUTE_FOUNDRY_CORE` creates no Factory Program and uses `version`, `validate-core`, `project-core-evidence`, and `package-local` directly.

## Request envelope

```json
{
  "request_id": "REQ-unique",
  "idempotency_key": "IDEM-unique",
  "program_id": "PROGRAM-safe-id",
  "expected_state_hash": null,
  "actor": {
    "type": "HUMAN_VIA_CODEX_CHAT",
    "chat_thread_id": "actual-task-id",
    "turn_id": "actual-user-turn-id"
  },
  "intent": "CREATE",
  "payload": {}
}
```

Use a fresh request ID and idempotency key for each different mutation. Reuse both only to replay the identical request. `CREATE` uses a null expected Hash; every later mutation uses the exact current `new_state_hash`.

```bash
python3 tools/hffactory.py chat-turn --request /absolute/path/request.json --json
```

After each Requirement mutation, use bounded Authoring progression:

```bash
python3 tools/hffactory.py advance-authoring-until-gate --program-id PROGRAM_ID --json
```

It advances deterministic internal work until `TRUE_GATE_ONLY`; it must not confirm locks, expand authority, or cross into execution.

## Intents

- `CREATE`: initialize one path-safe `program_id` and optional Requirement IR/sources.
- `ADD_SOURCES`: register absolute local paths or Hash-bound declared URIs.
- `UPDATE_REQUIREMENTS`: merge a Requirement IR patch.
- `ANSWER`: record answers and an optional `requirements_patch`.
- `PREPARE_READBACK`: close fixed-field gaps or return at most three blockers.
- `REQUEST_FREEZE`: create a challenge and exact confirmation token.
- `CONFIRM_FREEZE`: requires `challenge_id`, `requirement_ir_sha256`, `decision=APPROVE`, and the exact user-supplied `confirmation_text`.
- `GENERATE`: compile, validate in staging, atomically publish, and hard-stop.
- `REOPEN`: requires a non-empty reason and invalidates the old freeze/candidate.

Read-only commands:

```bash
python3 tools/hffactory.py status --program-id PROGRAM_ID --json
python3 tools/hffactory.py readback --program-id PROGRAM_ID --json
python3 tools/hffactory.py verify-run --program-id PROGRAM_ID --json
python3 tools/hffactory.py validate-candidate --program-id PROGRAM_ID --json
```

Authoritative run data is under `runs/PROGRAM_ID/`; derived JSON/JSONL views may always be regenerated from `factory.sqlite3`.
