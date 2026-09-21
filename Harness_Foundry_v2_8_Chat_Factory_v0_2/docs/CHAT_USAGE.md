# Codex Chat usage

Open this repository as the Codex project. The user-facing interface is natural language; the bundled repository skill operates the Factory CLI and persists all authoritative state.

## Start a program

Example:

> 为一个多阶段代码生成 Harness 创建符合 Harness Foundry v2.8 的宪章 Start Package。需求资料位于 `/absolute/path/to/requirements.md`，候选包输出到 `/absolute/path/to/output`。

Codex must register the request and sources before proposing normalized requirements. The Factory returns at most three high-priority questions per turn.

## Freeze requirements

When required fields, blocking questions, source conflicts, acceptance cases, and negative cases are closed, the Factory emits a readback and a freeze challenge bound to the current Requirement IR, Source Registry, and Spec Lock Hashes. It also returns an exact `confirmation_token`. Codex must show it and wait; only a later user message repeating that exact token may be submitted as `confirmation_text`.

Changing semantics after freeze creates a new epoch and invalidates the prior candidate attempt. If a candidate was already published, the old directory is preserved and `output_root` is cleared so the user must select a new empty path before another freeze.

## Resume in another Chat

Example:

> 继续 Factory Program `HF28-...`，先 readback 当前状态和合法下一动作。

Codex reads the SQLite-backed state by `program_id`; it must not reconstruct state from a prior chat summary.

## Candidate stop

Successful generation ends at:

```text
START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
AUTHORING_STOP
```

The same workflow must not approve or register the candidate, execute its Workpacks, start the generated Driver contract, build the three projects, install a Harness, or claim conformance.
