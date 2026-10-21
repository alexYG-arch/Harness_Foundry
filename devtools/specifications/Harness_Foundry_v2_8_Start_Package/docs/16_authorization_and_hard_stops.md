# 16｜授权模型与不可绕过的硬停止

> 状态：目标 Program 的权限规范。Markdown 中的“允许”不构成授权；只有符合 Schema、有效期、签发角色和当前 Hash 的机器授权资产可以被 Driver 消费。

## 1. 最小权限原则

自动推进的实际权限是以下集合的交集：

```text
role capability
∩ current execution mode
∩ DAG node allowed action
∩ PROGRAM_AUTOMATION_POLICY
∩ AUTHORIZATION_POLICY
∩ current EXECUTION_AUTHORIZATION
∩ command manifest scope
∩ path/environment side-effect boundary
```

任一项缺失、未知、冲突、过期或被撤销，结果都是拒绝。不得采用“其余条件都满足，所以推定批准”。

## 2. 授权资产分离

### 2.1 `AUTHORIZATION_POLICY.json`

定义长期规则：授权者角色、可委托范围、不可委托门禁、最大租期、允许模式、双人/独立审批要求、撤销和审计规则。它不批准某次执行。

### 2.2 `EXECUTION_AUTHORIZATION.json`

批准一次受控工程范围，至少绑定：

```text
authorization_id / policy_id / issuer_role / subject_role
program_id / control_plane_epoch / charter_hash / profile_lock_hash
project_ids / dag_node_ids / phase_ids / workpack_ids
execution_modes / command_ids and manifest hashes
allowed executable hashes / argv constraints
allowed read/write paths / target environment IDs
side_effect classes / secrets capabilities
not_before / expires_at / max transitions / loop budgets
required predecessor locks / input hashes
explicit exclusions / revocation ref / issuer integrity proof
```

它不能授权 `REAL_TARGET_INSTALL`，也不能包含通配的任意 shell、任意路径、任意环境或“所有后续任务”。

### 2.3 `REAL_TARGET_INSTALL_AUTHORIZATION.json`

这是独立、一次性、不可从执行授权继承的人工 Gate 资产，至少绑定：

```text
certified release lock + certificate + exact artifact hash
target environment identity and compatibility readback
install/upgrade action and exact command manifest
maintenance window / expected side effects
backup / rollback plan and rollback authority
post-install validation and acceptance owner
not_before / expires_at / one-time nonce
human approver identity and decision evidence
```

目标、Artifact、命令、窗口或回滚方案任何变化都需要新授权。批准测试环境不能推导为批准生产或其他真实目标。

## 3. 授权生命周期

```text
DRAFT
-> ISSUED
-> ACTIVE
-> CONSUMED | EXPIRED | REVOKED | INVALIDATED
```

授权一经 `CONSUMED/EXPIRED/REVOKED/INVALIDATED` 不得重新变为 ACTIVE。续期、扩围或换目标必须生成新 ID，并保留旧授权和撤销历史。

Driver 在每个 transition reservation 前、每个 command batch 前和结果 Promotion 前都重新校验授权。长任务中授权被撤销时，不启动下一批动作；当前不可安全中断动作按 policy 进入受控终止和 readback，不能继续到下一 Gate。

## 4. 模式与授权矩阵

| 动作/模式 | 可自动执行条件 | 不可委托门禁 |
| --- | --- | --- |
| `AUTHORING_ONLY` | 用户已发起 Authoring；仅 authoring allowlist | Candidate 完成后必须停，不能自动批准 |
| `PLAN_ONLY` | 只读、无副作用 | 不能把计划变成执行授权 |
| `REGISTRATION_ONLY` | 当前 target root 和注册命令获批 | 不激活首个 Workpack |
| 三工程 Bootstrap/Repair | `EXECUTION_AUTHORIZATION` 覆盖项目、Workpack、路径和工具 | Shared Baseline/Charter 冲突回人工 |
| `WORKPACK_EXECUTION` | 单 Active Workpack、有效前驱和命令授权 | 不能自动改 Profile、Charter、Acceptance |
| `PACKAGE_BUILD` | P4 Build Input Lock 和 isolated build 授权 | 不能签 Candidate/Certificate |
| `P4_INSTALLABILITY` | 精确 Artifact、全新临时环境、Installer 授权 | 不能声明 C4 或真实安装 |
| `CERTIFICATION_INSTALL` | Candidate Lock、唯一新环境、一次安装授权 | 失败后不能原地修复/重装 |
| `LINKAGE_READ_ONLY` | 固定工具/输入 Hash 和只读范围 | 不能修复、安装或签证 |
| `LAB_CERTIFICATION` | 固定 Candidate、环境、scenario/checker/attestation | Lab 不得修改被测 Harness |
| `REAL_TARGET_INSTALL` | 本次 `REAL_TARGET_INSTALL_AUTHORIZATION` | 永远保留人工审批 |

## 5. 必须由人工决定的 Gate

以下不得预设为 Driver 自批准：

1. Start Package Candidate、Program Charter、Profile 和 Shared Control Baseline 的首次批准；
2. Canonical Source 冲突、未决需求、范围改变和权威顺序变化；
3. Profile 降级/Program 重建；升级也需要新批准与失效传播；
4. P3 `NOT_APPLICABLE`；必须有证据、C3 和人工 Decision；
5. 安全/来源/意图保真/attestation 规则的任何例外或 waiver；
6. Loop 振荡、未知非幂等副作用、恢复结果不确定和跨权限修复；
7. 真实目标安装、升级、回滚及影响真实数据/服务的动作；
8. 授权扩围、延长、改变工具/Artifact/环境或重置 Loop epoch。

Human Decision 必须结构化记录批准/拒绝、范围、依据、时间、身份、绑定 Hash 和失效条件。聊天中的“继续”“应该可以”或 Agent 总结不能替代。

## 6. Authoring 硬门禁

Authoring 会话允许生成和静态验证 Start Package，但必须满足：

```text
execution_mode = AUTHORING_ONLY
execution_started = false
install_started = false
certification_started = false
active_workpack = null
auto_start_generated_workpacks = false
next_eligible_transition = HUMAN_REVIEW_OF_START_PACKAGE
```

Authoring Validator 不得运行生成的 Driver、初始化三工程 repo、构建 Lab/Linkage/Harness、注册 Program、安装工具或触发 Workpack。人工批准后必须开启新的执行边界并签发 `EXECUTION_AUTHORIZATION.json`；批准不能追溯性地把 Authoring 中发生的越权动作变合法。

## 7. 真实目标安装硬门禁

`P4_CERTIFIED_RELEASE_LOCK` 只说明 Release 可被考虑安装，不自动授予任何目标写权限。Driver 到达该 Lock 后必须进入：

```text
WAITING_REAL_TARGET_INSTALL_AUTHORIZATION
```

只有 Certification Installer 可以消费有效的 `REAL_TARGET_INSTALL_AUTHORIZATION.json`。消费前再次 readback：

- Certified Lock、Certificate、Artifact 和 Candidate Hash 一致且未撤销；
- 目标环境、兼容矩阵、容量、秘密、备份和回滚准备满足授权；
- 绝对 executable/argv、工作目录、side-effect boundary 与授权一致；
- 没有 active attempt、open blocker 或未传播 invalidation。

安装后必须生成 receipt、installed target descriptor、active instance manifest 和 post-install readback。安装成功不能修改旧 Certificate；失败不得自动重试，按人工回滚/恢复决定处理。

## 8. 通用硬停止条件

遇到以下任一条件，Driver 必须在下一副作用前停止：

### 8.1 状态与顺序

- Ledger 断链、state hash/epoch 不一致或存在未知转换；
- 两个 Active Workpack/Attempt、reservation 冲突或旧 fencing token；
- 前驱 Lock/Checkpoint 缺失、stale、撤销、属于其他 Program；
- P3 无 Build Lock 或获批 N/A Lock，或发布链顺序不合法；
- 下一合法写转换为零但流程声称可继续，或候选多于一个；
- touched、local closure、Candidate、Certified、Installed 状态被混写。

### 8.2 授权与命令

- Authorization 缺失、过期、撤销、epoch/Hash/角色/范围不匹配；
- 命令不在 Manifest、使用裸 shell、相对入口、未知 executable/hash；
- argv、cwd、环境变量、路径、目标环境或副作用超出授权；
- 命令需要秘密/网络/安装/删除权限而授权未明确包含；
- Actor 同时承担互斥的生成、安装、检查或签证角色。

### 8.3 证据与运行来源

- 证据缺失、不可读、Hash 不闭合、来源未知或仅为 self-report；
- Codex/LLM 必需 Stage 回退 Python、stub/mock 或无 Trusted Runner attestation；
- editable install、`PYTHONPATH`/PATH shadow、源码/Start Package/Driver 回退；
- Main、Linkage、Lab、Installer 消费的 Candidate/Pack/Artifact/工具版本不一致；
- Finding 未分配单一 Owner，或 invalidation 尚未传播。

### 8.4 Loop 与恢复

- retry/round/wall-time/evidence/side-effect budget 用尽；
- Finding 重现、A→B→A 状态振荡或持续无进展；
- Crash recovery 无法确定非幂等动作是否发生；
- 清理/回滚未确认，认证环境被污染，或授权在运行中撤销；
- 未知错误码、Schema 版本或恢复路径。

## 9. 硬停止输出契约

硬停止不能只打印异常文本。`PROGRAM_DRIVER_STATE.json` 和 append-only Ledger 至少记录：

```text
hard_stop_code / stopped_at / actor and driver identity
program/project/dag node/phase/workpack/attempt
last_valid_state_hash / last_valid_ledger_hash
authorization status / affected command ids
missing, stale, conflicting or unauthorized refs
known side effects / cleanup and environment isolation status
open findings / invalidation status
single allowed return path / required decision owner
capability claims explicitly not proven
```

阻断状态不得自动超时转 PASS。修复文件、补齐证据或新授权出现后，Driver 必须完整 revalidate，再通过合法 resume/reentry 事件离开。

## 10. 撤销与失效

授权撤销、Charter/Profile/Shared Baseline 变化、工具/Artifact Hash 变化或 Certificate 撤销必须写 append-only Revocation Ledger，并传播到：

```text
pending transitions and command attempts
-> active/queued Workpacks
-> Phase/Release locks
-> install/certification attempts
-> Certificate/Certified Release claim
-> pending Real Target Install Authorization
```

已发生的真实环境副作用不能通过删除状态文件撤回；必须生成 rollback/reconciliation Workpack 和人工 Decision。旧 evidence 保留为历史，但不得继续授权当前状态。

## 11. 明确禁止的授权模式

- Driver、Coding Agent、Lab、Linkage 或 Installer 自签发覆盖自身越权的授权；
- `allow_all=true`、任意 shell、任意路径、任意环境、无限有效期或无限 Loop；
- 把 PROGRAM_AUTOMATION_POLICY 当作某次执行授权；
- 用 Candidate Lock、Certificate 或用户最初的 Authoring 请求推导真实安装许可；
- 用成功结果倒推命令此前“应该被授权”；
- 授权被消费/撤销后修改时间或范围再次使用；
- 通过新会话、restart、rename Finding 或重建状态文件清除拒绝历史。

## 12. 最小负向验证

目标授权系统至少证明：

- Authoring Candidate 完成后不会自动激活 Workpack；
- 过期、撤销、错误 Program/epoch/Artifact/角色的授权均被拒绝；
- 同一授权不能越项目、越模式、越环境、越路径或越命令；
- P3 N/A 无人工 Decision 时不能推进；
- Lab/Linkage/Installer 越权行为不能产生可消费 PASS；
- `EXECUTION_AUTHORIZATION.json` 即使覆盖认证也不能覆盖真实安装；
- 真实安装授权更换目标、Artifact、窗口或命令后失效；
- Crash 后未确认的真实目标动作不会自动 retry；
- 任何 hard stop 都产生结构化 Return Path 且不能静默降级为 warning。
