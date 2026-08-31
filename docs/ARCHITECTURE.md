# Factory architecture

## 默认 Foundry 核心产品路径

```text
Requirement / Architecture inputs
  -> explicit readback and Hash-bound locks
  -> read-only compiled contract
  -> profile-driven Program Graph
  -> one Generic Transition Engine
  -> authoring or bounded runtime advance
  -> durable Checkpoint / Resume / Explain Stop
  -> portable local package and startup smoke
  -> official core validation and evidence projection
```

这条路径是 `SELF_USE_LOCAL_TRUSTED_OPERATOR` 的默认交付路线，共 41 项核心能力。它不依赖 Candidate、Execution Root、Runtime Bind、Program Driver、Workpack、A3、动态攻防、外部认证或安装。`validate-core` 只执行核心模块和核心失败路径；Manifest、Schema 或 Receipt 不能替代真实实现行为。

Slices 09–14 的 8 项 Candidate/Runtime 能力保留为非默认兼容扩展，`default_route=false`、`core_release_blocking=false`。它们的存在不扩大 Foundry 核心完成条件。

## 可选 Start Package 兼容架构

以下架构只在用户明确选择 Candidate Authoring 兼容路线时适用：

```text
User natural language
  -> Codex Chat
  -> repo AGENTS.md and harness-foundry-start-author skill
  -> hffactory JSON request envelope
  -> SQLite state/event/idempotency store
  -> frozen Requirement IR
  -> v2.8 hash-locked compiler
  -> same-filesystem staging
  -> read-only target candidate validator + bounded structural Hash repair
  -> evidence-backed internal Validation Report + second validation
  -> atomic candidate publication
```

Codex performs semantic interpretation and presents questions. The deterministic Factory owns state transitions, hashing, freeze challenges, compilation, validation, and publication. The Factory never calls another model.

The sibling v2.8 tree is normative and read-only. `spec_lock/HF28_SPEC_LOCK.json` binds its physical sibling name, package identity, version, exact file inventory, file hashes, aggregate content hash, and validator identity without exporting an author-machine absolute path.

Candidate generation consumes only the frozen Requirement IR, the spec lock, and explicit adjustment records. Chat history is not a generation input.

The canonical Requirement IR contains one `coverage_edges` record per Intent Atom. A user-confirmed explicit edge wins; otherwise the Factory derives a visible default from the Atom's Owner, phase/order markers, runtime/release semantics, and verification intent. The Readback freezes Atom-to-Workpack, Stage, optional Release Step, and owner-project routing together with the rest of the IR. The compiler cannot redirect it later.

Each Program owns `runs/<program_id>/factory.sqlite3`. Events include the resulting snapshot, so the append-only Hash chain can be checked against the current read model; State Hash CAS and idempotency keys prevent stale or duplicate Chat writes. Derived source, IR, decision, validation, readback, and JSONL event views are regenerated from SQLite.

The candidate embeds the frozen Requirement IR, Factory provenance, exact Spec aggregate Hash, traceability graph, runtime ownership, and mandatory negative controls. Compiler validation happens before publication. If a process dies after publication but before the SQLite commit, the same request can recover only a matching Factory-owned candidate with the same Requirement IR and Spec Hash; unrelated non-empty directories are never overwritten.

The engineering DAG expands Lab bootstrap/self-conformance/tool release, Linkage bootstrap/self-conformance/tool release, Main materialization/validation/registration, and G0/C0 through P4 into the fixed 20 nodes required by v2.8. Every node carries Owner, predecessor, Lock/Input/Tool Hash requirements, execution/authorization scope, read/write paths, environment, success output, failure return, invalidation, and allowed-next fields. Composite bootstrap nodes declare an ordered `project_workpack_sequence`; single-workpack nodes bind a real project-local `workpack_id`; control nodes declare only a `pipeline_action_id`. P3 is a machine-readable conditional between `MB-P3` and a separately human-approved N/A Lock action.

The three project indexes declare 16 project-local Workpacks. Their back-references and the forward bindings in the engineering DAG and release pipeline must cover all 16 exactly once. Unknown, cross-project, duplicated, reordered, or unbound references are blocking Findings. `MAIN_PROGRAM_REGISTRATION` is always a Driver-owned registration action with no Workpack and no Main repository write access; Main materialization and G0-P4 implementation nodes explicitly include the Main repository write root.

Each of those 16 Workpacks is materialized with a Markdown contract plus dedicated Command Manifest, Capsule, Result, and Loop State. The index records exact `requires`, the unique source of every required capability, `produces`, ordered Command IDs, artifact references, and content Hashes. Dependency sources must resolve to an earlier project Workpack, engineering DAG node, or release step that actually declares the capability. Project-level command manifests are non-empty and Hash-bound; planned Codex/tool/Driver interfaces keep `argv` unset until their CLI schema and preflight are verified, so the package neither guesses flags nor silently falls back to Python.

`RUNTIME_OWNERSHIP.json` separates the final target runtime, Build Program Driver, target-required executor/provider, and the Codex coding-agent executor. Every engineering coding Workpack binds the latter even when the target runtime itself is Python; Python verification commands cannot substitute for the Codex coding receipt.

The same Workpack index, Markdown, Command Manifest, Capsule, and Result carry the reverse `intent_atom_ids`. The validator checks these against the frozen coverage edges, Workpack phase compatibility, release-step identity, owner projects, scenarios, assertions, and evidence types. A P3/P4 Atom therefore cannot be silently redirected to G0, and a project Workpack cannot drop its implementing Atom while remaining green.

The P4 release manifest uses the complete fixed 23-node chain through installability environment, exact origin check, single certification environment, installed positive/negative/tamper tests, C4, Certificate, the separate real-install human Gate, installation receipt, and Active Instance Manifest. `LINK-PREFLIGHT`, `MB-RELEASE-CANDIDATE`, `LINK-D`, and `LAB-CERTIFICATION` are explicitly bound inside the appropriate release steps without adding an illegal 24th step or transferring promotion authority to a project Workpack.

All machine control assets share the same `program_id`, `profile_lock_hash`, `charter_hash`, `schema_version`, and `control_plane_epoch`; project state/command/index files carry the same binding. Any mismatch is a blocking validator Finding.
