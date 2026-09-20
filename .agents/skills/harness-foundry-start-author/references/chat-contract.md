# Factory Chat contract

Run all commands from the Factory repository root. Request files must be absolute paths. Each mutating call emits exactly one JSON object on stdout.

This contract belongs to `OPTIONAL_ROUTE_START_PACKAGE_COMPATIBILITY`. `DEFAULT_ROUTE_FOUNDRY_CORE` creates no Factory Program and uses `version`, `validate-core`, `project-core-evidence`, and `package-local` directly.

The upstream build-document policy in [the common contract](../../../../docs/GENERIC_BUILD_PLAN.md)
applies before entering this authoring route. Retain clarification Q&A, then save
and show the build document and obtain actual human confirmation of its version
and scope before CREATE or further build authoring. Internal completeness/PASS,
old approvals and delegated decisions cannot replace that review. Read-only
historical inspection remains allowed. CREATE requires payload.build_document_review
using the shared object in docs/GENERIC_BUILD_PLAN.md. Authoring mutations recheck
the bound full document. Only a human REOPEN may attach a replacement Review;
the delegate cannot approve this input on the user's behalf.

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
  "payload": {"build_document_review": "Supply the actual object from GENERIC_BUILD_PLAN.md; this example is not a valid request"}
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

## Opt-in delegated pre-build requests

The user must explicitly approve this protocol before a human grants it. Use
it only after the separate upstream build-document Human Review; the delegate
cannot perform that user decision. Historical grant records remain unchanged.
Use the existing envelope and actual user turn for `GRANT_PREBUILD_DELEGATION` with:
`delegation_id`, `decision=APPROVE`,
`scope=PREBUILD_AUTHORING_AND_CANDIDATE_DECISION`, current
`requirement_ir_sha256`, and the user's actual `approval_text`. The grant is
Program/Chat/source/intent scoped and creates no Candidate or execution authority.

Subsequent requests use an actual agent action turn, actor type
`CODEX_DELEGATED_AGENT`, and the persisted `delegation_id`. Do not submit human
tokens. Read current `delegated_next_allowed_intents` and State Hash.

- `REOPEN`: reason; invalidates old locks and decisions, preserving old files.
- `BIND_DELEGATED_OUTPUT`: empty payload; binds the grant's absent next epoch
  path without creating it. No caller root override is accepted.
- `ADVANCE_AUTHORING_UNTIL_GATE`: empty payload; prepare the full Readback.
- `DELEGATED_FREEZE`: decision=APPROVE, exact current requirement_ir_sha256 and
  readback_sha256. This records a delegated lock, not a human confirmation.
- `PREPARE_ARCHITECTURE_READBACK`: empty payload, when Architecture Lock applies.
- `DELEGATED_ARCHITECTURE_LOCK`: decision=APPROVE and architecture_readback_sha256.
- `GENERATE`: empty payload; consumes only the frozen output binding.
- `REVIEW_CANDIDATE`: decision=APPROVE or REJECT, candidate_content_sha256,
  requirement_ir_sha256, and review={summary, findings, reviewed_refs}.
  Findings require code, message and boolean blocking; reviewed_refs identify
  existing logical Candidate files. Perform the actual review before deciding.
  Approval requires fresh Validator PASS and no blocking findings.
- `REVOKE_PREBUILD_DELEGATION`: human only, delegation_id and reason.

Scope changes and revocation require a new human decision; a delegate cannot
call ANSWER/UPDATE_REQUIREMENTS/ADD_SOURCES or grant itself new authority.
Factory Producer repairs may still derive contracts from the unchanged intent.
All events remain in the existing SQLite audit chain; `verify-run` additionally
checks delegation relationships. A successful delegated Candidate decision is
external to the immutable Candidate, consumes the grant, and stops before
Harness construction/execution. It is never an EXECUTION_AUTHORIZATION.
