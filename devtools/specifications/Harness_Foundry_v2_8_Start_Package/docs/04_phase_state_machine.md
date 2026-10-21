# 04｜阶段状态机与锁链

## 1. 目的

本文件把 Harness 建设阶段从“推荐顺序”改为可校验的状态机。Coding Agent、Build Program Driver、校验器和人工 Gate 均不得仅凭文件存在、日志成功或阶段被触碰来推进状态。

相关规范：

- [Workpack 与执行模式](./05_workpack_and_execution_modes.md)
- [Agent 与 Runtime 权责](./06_agent_and_runtime_ownership.md)
- [意图保真与可追溯](./07_intent_fidelity_and_traceability.md)
- [构建、发布与安装](./09_build_release_install.md)

## 2. Profile 在 Charter 时锁定

`Full`、`Standard`、`Lite` 必须在 Program Charter 首次批准时选定，并写入 `PROGRAM_CHARTER_LOCK.json`。Profile 决定必需资产、Workpack 密度、审查强度和证据集，不改变前驱锁语义。

强制规则：

1. 所有 Phase Plan、Workpack、Lock、Checkpoint 和证据必须引用同一 `profile_id` 与 `profile_lock_hash`。
2. 开始 G0 后禁止从 Full 降为 Standard/Lite，也禁止从 Standard 降为 Lite。
3. 不能用“项目较小”“时间不足”或“当前检查已通过”进行事后降级。
4. 如确需降低范围，必须终止当前 Program，记录 `PROGRAM_TERMINATED`，创建新 Charter 和新 Program ID；旧证据不得继承为新 Program 的 PASS。
5. 向更严格 Profile 升级需要批准的 Charter Decision，并使所有受影响的下游计划、Workpack、Lock 和证据失效；升级不是原地改字段。
6. Standard/Lite 可以减少分片和 Workpack 数量，但不能删除 predecessor lock、外部 C1–C4、P3 决策、Transition Ledger、安装来源校验或 Conformance Gate。

## 3. 三类完成状态必须分离

每个阶段至少维护以下独立字段：

| 字段 | 含义 | 不得推导为 |
| --- | --- | --- |
| `touched` | 已创建或修改该阶段资产，或运行过该阶段任务 | 该阶段通过 |
| `locally_closed` | 该阶段全部 Outcome、Workpack、校验、Finding 和 Gate 在本地闭合 | 下游可发布 |
| `release_ready` | 已满足跨阶段、制品、安装、联通和独立认证条件 | 仅因本地测试成功 |

规则：

- `touched=true` 且 `locally_closed=false` 是正常中间态。
- `locally_closed=true` 只能由 Phase Gate 依据结构化证据设置。
- G0、P1、P2、P3 不设置 `release_ready=true`。
- P4 本地闭合只产生可构建输入；最终 `release_ready=true` 只能由 `P4_CERTIFIED_RELEASE_LOCK.json` 授权。
- 状态报告必须同时输出 `highest_touched_phase`、`highest_locally_closed_phase` 和 `release_ready`，禁止只报“已到 P4”。

## 4. 不可跳过的阶段链

固定链为：

```text
PROGRAM_CHARTER_LOCK
  -> G0 + C0 + G0_CONTROL_LOCK
  -> P1 local closure + C1 + P1_BUILD_LOCK
  -> P2 local closure + C2 + P2_BUILD_LOCK
  -> P3 local closure/N/A decision + C3
  -> (P3_BUILD_LOCK | P3_NOT_APPLICABLE_LOCK)
  -> P4 local closure + P4_BUILD_INPUT_LOCK
  -> Pack/Artifact/P4 Installability + P4_RELEASE_CANDIDATE_LOCK
  -> Installed Lab Certification + C4 + Certificate
  -> P4_CERTIFIED_RELEASE_LOCK
```

任何 Driver 必须先校验前驱 Lock 的存在、Schema、Hash、Program ID、Profile Lock、Charter Hash、输入 Hash 和未失效状态。文档中的阶段名称、目录存在或测试 PASS 均不能替代前驱 Lock。

## 5. 本地 Gate、外部 Checkpoint 与输出锁

| 状态 | 必需前驱 | 本地 Gate | 阻断式外部 Checkpoint | 成功输出 |
| --- | --- | --- | --- | --- |
| G0 | 有效 `PROGRAM_CHARTER_LOCK` | G0 Control Gate | C0：Conformance Contract/Interface | `G0_CONTROL_LOCK` |
| P1 | 有效 `G0_CONTROL_LOCK` + C0 PASS | P1 Architecture Gate | C1：Stage/Runtime/Receipt Conformance | `P1_BUILD_LOCK` |
| P2 | 有效 `P1_BUILD_LOCK` + C1 PASS | P2 Vertical Slice Gate | C2：Slice Conformance，禁止把 slice 冒充 general runner | `P2_BUILD_LOCK` |
| P3 | 有效 `P2_BUILD_LOCK` + C2 PASS | P3 Expansion/N/A Gate | C3：Outcome Coverage、Runtime Ownership、Orchestration Coverage | `P3_BUILD_LOCK` 或 `P3_NOT_APPLICABLE_LOCK` |
| P4 构建输入 | 有效 P3 Lock + C3 PASS | P4 Integration/Build Input Gate | C4 尚不可执行 | `P4_BUILD_INPUT_LOCK` |
| P4 认证发布 | 有效 Candidate Lock + 已安装认证环境 | 不适用 | C4：Installed E2E、Negative Acceptance、Release Certificate | `P4_CERTIFIED_RELEASE_LOCK` |

C0–C4 是外部认证轨道，不是 P1–P4 的另一个名称，也不是普通开发日志标签。它们必须由独立、可读取、带 Hash 的 Checkpoint Report 表达。Checkpoint 至少绑定：

- Program、Charter、Profile、Phase 与前驱 Lock；
- 本阶段 Outcome Atom、Workpack Result 和 Finding Closure；
- 执行命令账本、环境标识与证据 Hash；
- Gate 判定、判定者、时间和失效条件。

P1–P3 Phase Lock 必须引用对应 C1–C3 Hash；`G0_CONTROL_LOCK` 引用 C0 Hash。`P4_BUILD_INPUT_LOCK` 只证明 P4 本地可构建输入，不能引用尚未执行的 C4；最终 `P4_CERTIFIED_RELEASE_LOCK` 必须引用 C4 Report 和 Certificate Hash。下游同时校验 Lock 与相应 Checkpoint，不能只校验其一。

## 6. P3 不适用仍然是一个显式状态

不得把 P3 目录留空、从计划中删除或直接执行 P4。P3 不适用时必须完成：

1. 证明 Charter 中不存在需要独立扩展的 Sub-harness 或适配面；
2. 给出 Outcome Atom、运行路径和扩展点的完整覆盖证据；
3. 记录风险、未来触发条件和批准人；
4. P3 本地 Gate 和外部 C3 都接受并绑定 `PASS_WITH_NOT_APPLICABLE_DECISION`；
5. 生成 `P3_NOT_APPLICABLE_LOCK.json`。

`P3_NOT_APPLICABLE_LOCK` 与 `P3_BUILD_LOCK` 在状态机中是互斥合法前驱，但前者不是“跳过证明”。若后续新增 Sub-harness，P3 N/A Lock 及全部下游资产必须失效，重新进入 P3。

## 7. Lock 最小结构

```json
{
  "lock_id": "P2_BUILD_LOCK-...",
  "lock_type": "P2_BUILD_LOCK",
  "program_id": "...",
  "phase": "P2",
  "profile_id": "Standard",
  "profile_lock_hash": "sha256:...",
  "charter_hash": "sha256:...",
  "predecessor_lock_id": "P1_BUILD_LOCK-...",
  "predecessor_lock_hash": "sha256:...",
  "checkpoint_id": "C2-...",
  "checkpoint_hash": "sha256:...",
  "evidence_manifest_hash": "sha256:...",
  "status": "VALID",
  "created_at": "..."
}
```

Lock 文件自身不得包含可被后续补填的循环引用。Release Candidate 与 Certified Release 的绑定见[构建、发布与安装](./09_build_release_install.md)。

## 8. Append-only Transition Ledger

所有状态变化写入 `phase_transition_ledger.jsonl`。账本只追加，不覆盖、不删除、不就地改写旧事件。每行必须包含：

```json
{
  "event_id": "...",
  "sequence": 42,
  "previous_event_hash": "sha256:...",
  "program_id": "...",
  "profile_lock_hash": "sha256:...",
  "from_state": "P2_LOCALLY_CLOSED",
  "to_state": "P3_ACTIVE",
  "predecessor_lock_id": "P2_BUILD_LOCK-...",
  "authorization_ref": "...",
  "evidence_refs": ["..."],
  "actor_role": "BUILD_PROGRAM_DRIVER",
  "timestamp": "...",
  "event_hash": "sha256:..."
}
```

账本校验必须检查序号连续、前项 Hash 链、合法转换、Actor 权限、证据可读和引用 Lock 有效。发现断链、重排、重复序号或未知转换时，状态为 `TRANSITION_LEDGER_INVALID`，不得继续。

## 9. 合法转换

```text
PLANNED -> ACTIVE -> TOUCHED -> LOCALLY_CLOSED -> LOCKED
LOCKED -> INVALIDATED -> REWORK_PLANNED -> ACTIVE
P4_BUILD_INPUT_LOCKED -> PACK_PREFLIGHT_PASS -> ARTIFACT_BOUND
ARTIFACT_BOUND -> INSTALLABILITY_PASS -> CANDIDATE_READY
CANDIDATE_READY -> INSTALLED_CERTIFICATION_ACTIVE -> C4_PASS
C4_PASS -> CERTIFIED_RELEASE_READY
```

以下转换永远非法：

- P1/P2 直接进入 P4；
- P2 直接进入 P4，即使 P3 被声明为“不需要”；
- `TOUCHED -> LOCKED`；
- `LOCALLY_CLOSED -> CERTIFIED_RELEASE_READY`；
- 失效 Lock 重新变为 VALID；
- 用新证据回填旧 Ledger 事件。

## 10. 失效传播

上游 Authority、Charter、Profile、Outcome、Spec、代码、Schema、Checkpoint 或 Lock 变化时，必须创建新的 `INVALIDATED` 事件，并按依赖图失效所有下游：

```text
阶段 Lock
-> 下游 Phase Plan / Workpack / Capsule
-> P4 Build Input
-> Pack B0/B1 Binding
-> Release Artifact / Candidate Lock
-> Install Evidence / Certificate
-> Certified Release Lock
```

失效不是删除历史。旧资产保留为审计记录，但任何 Gate 都必须拒绝其作为当前证据。

## 11. Driver 的机械拒绝条件

遇到以下任一情况必须停止，不得“按合理理解继续”：

- Profile 未锁定、被降级或与 Workpack 不一致；
- 前驱 Lock 缺失、Hash 不一致、已失效或属于其他 Program；
- 当前转换所需的 C0–C4 缺失或不处于其 Schema 允许的终态 PASS（含获批的 P3 N/A 终态）；
- P3 既无 Build Lock 也无 N/A Lock；
- 同时激活多个 Workpack；
- Transition Ledger 不能验证；
- `touched` 被当作 `locally_closed`；
- Candidate Lock 被当作 Certified Lock；
- 运行入口来自 Build Program 而非最终 Harness。

拒绝结果必须包含机器码、缺失证据、当前状态和唯一允许的返回路径。

## 12. 与受控自动推进的关系

Phase 状态机只决定阶段边是否合法，不单独授予执行。Program Driver 还必须同时验证：

1. `ENGINEERING_PROJECT_DAG` 中当前工程节点 ready；
2. `PROGRAM_AUTOMATION_POLICY` 允许该节点自动执行；
3. `EXECUTION_AUTHORIZATION` 覆盖当前 mode、Workpack、命令、路径和环境；
4. `PROGRAM_DRIVER_STATE` 没有 active lease、open hard stop 或 stale snapshot；
5. next-action selector 得到且只得到一个合法动作。

Workpack PASS 后，Driver 可以在同一有效授权范围内推进下一个节点；Promotion、Phase Lock、模式切换和跨工程 barrier 仍必须分别产生 Ledger 事件。出现零个合法动作时进入 `WAITING` 或 `BLOCKED`；出现多个动作时返回 `AMBIGUOUS_NEXT_ACTION`，不得猜测顺序。

详细规则见[受控自动推进](./13_controlled_auto_progression.md)和[Program Driver、Loop 与恢复](./15_program_driver_loop_and_recovery.md)。
