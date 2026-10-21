# 13｜受控自动推进控制平面

> 状态：目标 Start Execution Package 的生成规范，不是已部署的 Driver。生成者必须把本规范实例化为机器文件、程序入口、测试和证据；本文存在不等于自动推进已经实现。

## 1. 定义与边界

受控自动推进是指：在目标 Start Package 获得人工批准后，Build Program Driver 根据当前可验证状态，从预先批准的有向图中选择唯一合法动作，只执行结构化 Command Manifest 和有效授权共同允许的命令，并自动运行到下一个人工门禁、硬停止或终态。

它不表示：

- Authoring 完成后自动执行刚生成的 Workpack；
- Agent 自行批准 Charter、Profile、例外或 P3 N/A；
- 用测试退出码、文件存在或模型自述自动生成 Lock/Certificate；
- 自动改变真实目标环境；
- 为了继续推进而猜测缺失状态、扩大权限或跳过 P3；
- 把 Build Program Driver 当作最终 Harness Runtime。

Authoring 交付必须保持 `execution_mode=AUTHORING_ONLY`、`auto_start_generated_workpacks=false`，并停在 `START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW`。离开该状态必须有独立人工批准事件。真实目标安装始终需要本次目标专用的人工授权，见[授权与硬停止](./16_authorization_and_hard_stops.md)。

## 2. 必需的机器控制资产

目标包必须实例化并相互引用：

| 资产 | 唯一责任 |
| --- | --- |
| `THREE_PROJECT_PROGRAM_MANIFEST.json` | 三工程身份、根目录、版本、工具分发、输入输出和信任边界 |
| `ENGINEERING_PROJECT_DAG.json` | 三工程搭建节点、前驱、成功输出、失败回流和允许后继 |
| `RELEASE_PIPELINE_MANIFEST.json` | P4 后 Pack、Artifact、安装、D、C4、Certificate 的固定链 |
| `PROGRAM_DRIVER_CONTRACT.json` | Driver 入口、状态算法、Ledger、命令协议和拒绝码 |
| `PROGRAM_DRIVER_STATE.json` | 当前 epoch、状态、唯一 Active Workpack/Attempt、blocker 和下一动作 |
| `PROGRAM_AUTOMATION_POLICY.json` | 允许自动推进的模式、边界、并发、预算和停止策略 |
| `AUTHORIZATION_POLICY.json` | 哪个角色可以为哪种动作授权，以及不可委托门禁 |
| `EXECUTION_AUTHORIZATION.json` | 当前自动执行租约；绑定范围、Hash、模式、命令和有效期 |
| `LOOP_POLICY.json` / `LOOP_STATE.json` | 重试、Review/Fix、Repair、振荡、升级和恢复状态 |
| `FINDING_SCHEMA.json` / `REPAIR_ROUTING_RULES.json` | Finding 结构和单一修复 Owner |
| `INVALIDATION_DAG.json` / `REENTRY_PLAN.json` | 失效传播和从最早受影响门禁重入 |

这些文件的 `program_id`、`profile_lock_hash`、`charter_hash`、`schema_version` 和 control-plane epoch 必须一致。Markdown 只解释语义，不能替代机器资产。

执行副作用前还必须完成 `CONTROL_PLANE_REGISTRATION` 和 `PROGRAM_DRIVER_RUNTIME_VERIFIED`。Driver 可以是独立 Foundry Runtime 或受控 Codex Driver，但必须有可核对入口、版本、权限、状态/lease/幂等实现和验证证据；Final Harness Runtime 永远不能承担该角色。

## 3. 自动化等级

| 等级 | 能力 | 是否可连续自动执行 |
| --- | --- | --- |
| `A0_DECLARE_ONLY` | Authoring、生成计划、静态校验 | 否；必须停在人工审查 |
| `A1_PLAN_ONLY` | 只读计算唯一下一动作和缺失条件 | 可自动计算，不可执行副作用 |
| `A2_WORKPACK_BOUNDED` | 单个已授权 Workpack 及有界 Review/Fix | 可执行到 Workpack 终态 |
| `A3_PROGRAM_BOUNDED` | 三工程搭建、阶段链、构建、隔离安装与认证 | 仅在授权覆盖且无硬门禁时连续执行 |
| `A4_REAL_TARGET` | 真实目标安装、升级、回滚 | 不继承 A3；每次需要独立人工授权 |

`A3_PROGRAM_BOUNDED` 不是通配权限。每个模式、项目、环境、命令、路径、有效期和最大循环数仍必须落在 `EXECUTION_AUTHORIZATION.json` 内。

## 4. 全局单 Active Workpack

三工程共用一个 Program 控制平面。任意时刻：

```text
count(workpack.status == ACTIVE across Main + Lab + Linkage) <= 1
PROGRAM_DRIVER_STATE.active_workpack_id == that Workpack ID or null
```

规则：

1. Workpack 激活必须先获得原子 reservation，再写 append-only Transition Ledger。
2. 激活 Lab 或 Linkage 的建设/修复 Workpack 时，Main Workpack 必须为空；反之亦然。
3. 同一 Workpack 可以使用多个 Agent 提供只读分析，但只有一个 Candidate Workspace 和一个写 Owner。
4. 对同一不可变快照的无副作用只读校验可以并发；它们不是 Active Workpack，且不得 Promotion、修复或推进状态。
5. P4 Installability、Certification Install、D/C4 使用唯一 `active_attempt_id` 串行化；不得与修改相关输入的 Workpack 并行。
6. 检测到两个 Active Workpack、两个 canonical Certification Attempt 或状态文件与 Ledger 不一致时，立即进入 `STATE_CONFLICT_HARD_STOP`。

## 5. 当前状态的确定性选择

Driver 每次 tick、resume 或进程重启都按以下优先级选择状态；不得让 LLM 自由决定下一步：

1. 校验 Program/Profile/Charter、Schema、Ledger Hash 链和 control-plane epoch；失败则硬停止。
2. 若存在未完成的 transition intent 或 command attempt，进入 `RECOVERY_REQUIRED`，先对账，不选择新动作。
3. 若存在未传播的 invalidation/revocation，进入 `INVALIDATION_REQUIRED`，先完成传播。
4. 若当前处于不可委托人工 Gate，进入 `WAITING_HUMAN_GATE`。
5. 若 Loop 已超预算、出现振荡或有未解决 blocker，进入 `ESCALATED` 或相应 `BLOCKED_*`。
6. 若有唯一 Active Workpack，只能恢复、完成、失败或释放该 Workpack。
7. 若有唯一 Active Attempt，只能继续、对账、终止并清理该 Attempt。
8. 否则从当前 DAG 节点枚举合法后继，并过滤前驱 Lock、输入 Hash、工具版本、环境、Execution Mode 和授权。
9. 候选为零：返回精确 `WAITING_*`/`BLOCKED_*`；候选多于一个：返回 `AMBIGUOUS_NEXT_TRANSITION`；恰好一个才可 reservation。

候选排序不能把本来歧义的两个写动作强行变成唯一动作。只有 DAG 明确声明的互斥分支条件和优先级可以消除歧义。

## 6. 一次推进的事务协议

```text
read immutable control snapshot
-> validate state and authorization
-> select exactly one transition
-> append TRANSITION_INTENT with idempotency key
-> reserve Workpack or Attempt
-> execute authorized command attempts
-> collect stdout/stderr/readback/evidence hashes
-> independent postflight and acceptance
-> write WORKPACK_RESULT or pipeline result
-> promote, invalidate, block, or return
-> append transition outcome
-> atomically publish new PROGRAM_DRIVER_STATE
-> release reservation
```

每次推进都必须绑定旧 state hash 和新 state hash。状态发布失败时，不得仅凭命令退出码重跑；必须按[Driver Loop 与崩溃恢复](./15_program_driver_loop_and_recovery.md)对账。

## 7. 连续运行语义

Driver 可以提供以下语义，但入口必须由 `PROGRAM_DRIVER_CONTRACT.json` 定义为绝对路径和结构化 argv：

- `plan-next`：只读返回唯一下一动作、缺失条件或硬停止；
- `advance-one`：最多提交一个状态转换；
- `advance-until-gate`：循环执行唯一合法转换，直到人工 Gate、hard stop、预算耗尽或终态；
- `resume`：只恢复已有 Program/Workpack/Attempt，不隐式创建新授权；
- `status`：同时报告 touched、locally closed、release candidate、certified 和 installed 状态。

连续运行必须设置 `max_transitions`、`max_wall_time` 和 Loop budget。达到预算是正常 `PAUSED_BUDGET_EXHAUSTED`，不是 PASS，也不得自动续租权限。

## 8. Promotion 与证据责任

Coding Agent、命令退出码和 Driver 本身均不能自我证明最终 PASS。自动 Promotion 只允许在：

1. 权威 validator 读取当前不可变输入；
2. 所需正向、负向、来源和意图保真测试均产生结构化证据；
3. Finding closure、Command Ledger、环境清理和副作用 readback 完整；
4. Promotion 角色、Schema 和签名/完整性机制符合当前 Gate；
5. Ledger 中不存在更新的 invalidation/revocation。

任何 `UNKNOWN`、证据不可读或 Hash 不一致都按 FAIL/NOT_CERTIFIABLE 处理。自动推进只能消费 Gate 结果，不能降低 Gate 标准。

## 9. 最小状态输出

每次 `status` 至少输出：

```text
program_state / control_plane_epoch
current_project / current_dag_node / current_phase
highest_touched_phase / highest_locally_closed_phase
active_workpack_id / active_attempt_id
current_execution_mode / authorization_id / authorization_status
valid_locks / invalidated_locks / open_findings
loop_round / retry_budget_remaining / oscillation_status
next_eligible_transition / why_not_eligible
waiting_human_gate / hard_stop_code / required_return_path
release_candidate_ready / certified_release_ready / real_target_installed
```

禁止把 `highest_touched_phase=P4`、Candidate Ready 或 Certification Install Active 表述为 Harness 已认证或真实安装。

## 10. 自动推进就绪条件

只有以下全部有真实实现和负向测试时，目标工程才可声明 `CONTROLLED_AUTO_PROGRESS_READY`：

- 本文机器资产可解析且 Hash/引用闭环；
- 三工程 DAG 与发布链可机械枚举且无环；
- 全局单 Workpack/Attempt 可在并发和崩溃场景下保持；
- 授权缺失、过期、越界和撤销均能阻断；
- retry、oscillation、escalation、resume 和 crash recovery 已验证；
- P3 skip、错误入口、源码回退和自动真实安装的负向用例全部拒绝；
- 状态和证据可由新会话 readback，不依赖聊天记忆。

Start Package 仅生成上述计划或模板时，状态必须为 `AUTO_PROGRESS_PLANNED_NOT_IMPLEMENTED`。
