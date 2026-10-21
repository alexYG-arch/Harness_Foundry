# 15｜Program Driver Loop、重试与崩溃恢复

> 状态：目标 Driver 的运行契约，不是可执行脚本。生成者必须创建 `PROGRAM_DRIVER_CONTRACT.json`、状态实现、Ledger、命令适配器和测试，未实现前标记 `PLANNED_NOT_RUN`。

## 1. Driver 的唯一职责

Build Program Driver 负责读取状态、机械选择唯一合法转换、激活一个 Workpack/Attempt、调用受控 Runner、提交结果并在异常时停止或恢复。它不负责：

- 编写业务实现或修复 Finding；
- 判断 Codex/LLM 是否真实调用；
- 降低 Acceptance、签发 Certificate 或批准自身；
- 代替 Final Harness Runtime；
- 自动扩大授权、生成真实安装授权或清理不明副作用。

## 2. Driver 状态机

`PROGRAM_DRIVER_STATE.json` 的 `driver_status` 必须使用封闭枚举：

```text
AUTHORING_STOPPED
WAITING_HUMAN_GATE
IDLE
SELECTING
TRANSITION_RESERVED
WORKPACK_ACTIVE
COMMAND_ATTEMPT_ACTIVE
POSTFLIGHT_ACTIVE
PIPELINE_ATTEMPT_ACTIVE
RETRY_PENDING
REPAIR_REQUIRED
INVALIDATION_REQUIRED
RECOVERY_REQUIRED
PAUSED_BUDGET_EXHAUSTED
BLOCKED
ESCALATED
COMPLETED_TO_GATE
PROGRAM_TERMINATED
```

状态至少绑定 `state_hash`、`control_plane_epoch`、`last_ledger_event_hash`、`active_workpack_id`、`active_attempt_id`、`transition_intent_id`、`authorization_id`、`loop_state_ref` 和 `blocker_codes`。

任何无法映射到封闭枚举的内部异常必须变为 `BLOCKED` + `UNKNOWN_DRIVER_FAILURE`，不能默认回到 `IDLE`。

## 3. 主循环

```text
load and hash state
-> reconcile unfinished intent/attempt
-> propagate pending invalidation
-> evaluate human gates and authorization
-> resume active Workpack/Attempt or select one legal transition
-> reserve
-> execute one bounded action batch
-> postflight/readback
-> commit outcome and state
-> evaluate loop budget and next hard gate
```

`advance-until-gate` 只是重复上述有限事务。每一轮最多提交一个 DAG transition；不得把多个 shell 命令串成不可观察的“全流程脚本”。

## 4. 四类 Loop

### 4.1 Workpack Execution Loop

每轮执行当前 Workpack 的一个获批 command batch，生成 Command Attempt 和 evidence。Workpack 只有在所有 Acceptance/Postflight 完成且生成 `WORKPACK_RESULT.json` 后才结束。

### 4.2 Review/Fix Loop

Reviewer 只读登记 Finding；Fixer 只处理当前 Workpack、当前 intent、允许写路径内的 OPEN Finding。每轮为：

```text
review immutable candidate
-> register findings
-> select bounded in-scope findings
-> fix in candidate workspace
-> rerun affected acceptance
-> independent review
```

Loop converged 只表示没有新的 in-scope Finding，不等于 Workpack PASS、Phase Lock 或 Promotion。

### 4.3 Release/Certification Loop

发布链不是“失败后原地重试”循环。Artifact、Candidate 或认证环境变化后必须创建新 identity/Attempt，并按 `REENTRY_PLAN.json` 从最早门禁重入。认证环境失败后销毁，禁止覆盖安装继续 C4。

### 4.4 Finding Repair Loop

Finding 必须经过：

```text
TRIAGED
-> single owner assigned
-> downstream invalidated
-> Repair Workpack active
-> locally repaired
-> required rebuild/reinstall/recertify
-> independent closure
```

`REPAIR_ROUTING_RULES.json` 和 `INVALIDATION_DAG.json` 决定 Owner 与重入，不由当前 Agent 临时选择。

## 5. Loop Policy 必需字段

`LOOP_POLICY.json` 至少定义：

```text
policy_id / program_id / control_plane_epoch
loop_type / applicable_modes / authorization_requirement
max_rounds / max_command_attempts / max_wall_time
retryable_error_codes / non_retryable_error_codes
retry_delay_policy / cleanup_before_retry
finding_fingerprint_fields / oscillation_rules
evidence_growth_limit / side_effect_limit
escalation_owner / escalation_artifacts
resume_requirements / terminal_states
```

`LOOP_STATE.json` 记录当前 round、attempt、输入 Hash、Finding 指纹历史、状态序列、预算余额、清理 receipt、最近进展证明和 escalation reason。不得只在内存或聊天中计数。

## 6. 重试规则

只有同时满足以下条件才可自动 retry：

1. 错误码位于预先批准的 `retryable_error_codes`；
2. 输入、授权、命令定义和目标状态未变化；
3. 上次 attempt 的副作用已 readback 并清理，或命令被证明幂等；
4. retry 不会复用失败的 Certification Environment；
5. retry budget 尚未耗尽；
6. 没有新 Finding、invalidation、撤销或人工 Gate。

允许的典型 retry 是受控临时故障，如 Runner transport 暂时失败且未启动副作用。以下不得自动 retry：

- Schema/Hash/Lock/Authorization 不匹配；
- Acceptance、负向测试或 C4 语义失败；
- Codex/LLM 调用未被见证、nonce 重放或输出绑定失败；
- 安装来源回退源码、editable/PATH shadow；
- 未知是否已执行的非幂等安装、迁移、发布或签发动作；
- 人工拒绝、授权过期/撤销、Profile/Charter 冲突。

Retry 不能改变 executable、argv、环境、输入或 Acceptance。需要改变任何一项时，必须结束当前 Attempt，创建 Finding/Repair 或新的授权，不得把它记作 retry。

## 7. 进展、停滞与振荡

每轮必须计算 `progress_vector`，至少包含：

```text
closed_finding_ids
new_finding_ids
acceptance_pass_set_hash
candidate_diff_hash
remaining_required_outputs
current_dag_node and lock set
```

Finding 指纹至少组合：`error_code + earliest_invalid_node + affected_intent_atom_ids + normalized_evidence_signature`。

必须停止并 `ESCALATED`：

- 同一 Finding 指纹在声称关闭后再次出现达到 policy 阈值；
- 状态或 Candidate Diff 在 A→B→A 间重复；
- 连续轮次没有减少 blocker/required output，也没有新增有效证据；
- 修复一个 Finding 稳定地重开另一个已关闭 Finding；
- 达到 max rounds、attempts、wall time、evidence 或 side-effect budget。

不得通过重命名 Finding、改变日志文本或清空 Loop State 绕过振荡检测。新授权也不能删除历史指纹；只能由 Human Gate 批准新的 policy epoch。

## 8. Escalation 契约

`ESCALATED` 必须冻结写动作并输出：

- 当前 Program/Project/Phase/Workpack/Attempt；
- 最后有效 State/Ledger Hash；
- 触发码、Finding 指纹和状态序列；
- 已尝试轮数、命令、Diff 与副作用；
- 未清理环境或不确定动作；
- 唯一允许的 owner、Return Path 和待人工决定事项；
- 恢复所需的新授权、重基线或 Repair Workpack。

Escalation 不是 FAIL 豁免。只有结构化 Human Decision 或已验证的 Repair/Rebaseline 事件可以离开该状态。

## 9. 命令 Attempt 与幂等键

每条命令执行前写 `COMMAND_ATTEMPT_RESERVED`，幂等键至少绑定：

```text
program_id + control_plane_epoch
+ dag_node + workpack_id/pipeline_attempt_id
+ command_id + command_manifest_hash
+ locked_input_set_hash
+ target_environment_id
+ authorization_hash
+ logical_attempt_number
```

同一幂等键只能产生一个 canonical outcome。重复提交者必须读取已有 outcome；不能再次启动进程。

命令按恢复能力分类：

| 分类 | 崩溃后策略 |
| --- | --- |
| `READ_ONLY_IDEMPOTENT` | 对账后可用同输入新 attempt 重跑 |
| `ISOLATED_BUILD_RECREATABLE` | 丢弃未发布输出目录，新 identity 重建 |
| `INSTALL_ATTEMPT_UNIQUE` | 检查环境/receipt；不确定则隔离销毁，新环境重入 |
| `CERTIFICATION_EFFECT_UNIQUE` | 检查 nonce、attestation、certificate ledger；绝不盲重发 |
| `REAL_TARGET_NON_IDEMPOTENT` | 始终人工恢复/回滚；禁止自动重试 |

## 10. 崩溃恢复协议

Driver 启动时先恢复，不先选择 next：

1. 校验最后完整 Ledger 事件与 `PROGRAM_DRIVER_STATE.state_hash`；
2. 查找无 outcome 的 Transition Intent、reservation 和 Command Attempt；
3. 对实际进程、环境、文件、安装分发、receipt、attestation 和证书账本执行只读 readback；
4. 将每个未决动作分类为 `NOT_STARTED`、`RUNNING_VERIFIED`、`COMPLETED_VERIFIED`、`FAILED_VERIFIED` 或 `OUTCOME_UNKNOWN`；
5. `COMPLETED_VERIFIED` 可以提交原结果；`NOT_STARTED` 只有授权仍有效时才可启动；
6. `RUNNING_VERIFIED` 只能继续观察或按 policy 安全终止；不得启动第二实例；
7. `OUTCOME_UNKNOWN` 的非幂等动作进入硬停止；安装/认证环境必须隔离，不得被后续复用；
8. 写 Recovery Ledger 事件并原子发布新状态后，才允许恢复主循环。

禁止仅因 PID 不存在就判断命令未执行，也禁止仅因输出文件存在就判断成功。

## 11. 原子状态与并发防护

- 状态写入使用 compare-and-swap 或等价的 old-state-hash 条件更新；
- reservation 包含 owner、lease、heartbeat 和 fencing token；过期 lease 只能触发对账，不能自动取得写权；
- 所有副作用执行者验证最新 fencing token；旧 Driver 即使恢复也不能提交；
- Ledger 先记录 intent，后记录 outcome；状态文件是缓存视图，Ledger 是审计来源；
- Promotion/Revocation 必须有独立 append-only ledger，不得覆盖旧 PASS；
- control-plane epoch 改变时，旧 lease、授权、resume token 和未开始命令全部失效。

## 12. Resume 契约

`resume` 必须显式指定 Program 和预期 state hash，并满足：

- 当前不是 Authoring Stop 或未满足的人工 Gate；
- 授权仍有效并覆盖剩余动作；
- 未决 recovery/invalidation 已处理；
- Workpack/Candidate/Attempt 输入 Hash 未变化；
- Loop budget 未被重置或绕过；
- resume actor 有权恢复该模式。

Resume 不自动创建 Workpack、延长授权、关闭 Finding、更新工具版本或选择新的修复路径。条件不满足时返回精确阻断码和唯一 Return Path。

## 13. 最小负向测试

目标 Driver 至少验证：

- 两个进程竞争同一 Workpack 时只有一个 reservation 成功；
- Driver 在命令启动后、结果提交前崩溃，不会重复非幂等动作；
- 旧 fencing token 不能提交结果；
- 认证安装崩溃且结果未知时不会覆盖安装或复用环境；
- 同 Finding 重现与 A→B→A 状态振荡会升级；
- Loop budget 用尽后不会因 restart/resume 清零；
- 授权在 Loop 中撤销会立即停止下一 command batch；
- Recovery 不能把文件存在、退出码 0 或 Agent 自述当作 PASS；
- Real Target 安装失败不会自动 retry。
