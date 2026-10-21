# 14｜三工程搭建 DAG 与发布链

> 状态：目标三工程 Program 的机器流程规范。本文规定顺序，不证明 Lab、Linkage、Main Harness 或 Driver 已经创建、安装或通过校验。

## 1. 三工程与控制平面

受控 Program 包含三个工程：

1. `FOUNDRY_CONFORMANCE_LAB`：独立权威 Checker、Trusted Runner 协议、测试和 Certificate；
2. `CONFORMANCE_LINKAGE_REVIEW`：独立、只读 A/B0/B1/C/D 联通审查和 Repair Route；
3. `MAIN_HARNESS_BUILD_PROJECT`：Main Harness 执行包、阶段实现、Pack、Artifact 与修复。

Build Program Driver、Certification Installer 和状态/Ledger 是控制平面角色，不构成第四个认证工程。三个工程的路径、仓库身份、分发包、版本、入口和读写边界必须写入 `THREE_PROJECT_PROGRAM_MANIFEST.json`，不得靠相邻目录名推断。

## 2. 不可变共享基线

三工程建设前必须形成由 Human Gate 批准的共享基线：

```text
Program Charter + Profile Lock
+ Protocol / Schema versions
+ ID namespace and closed error-code registry
+ compatibility matrix
+ evidence / attestation contract
+ project roots and trust boundaries
= SHARED_CONTROL_BASELINE_LOCK
```

Authoring 会话只生成 Candidate 和校验报告，必须在 `AUTHORING_APPROVAL` 停止。`SHARED_CONTROL_BASELINE_LOCK` 只有在该人工批准后才可生效；Driver 不得自己签发批准，也不得把文档生成时间当作批准时间。

每个下游节点都绑定 baseline hash。基线变化必须失效所有受影响工程版本、Workpack、报告、Artifact、Certificate 和安装授权。

## 3. 工程建设的固定 DAG

`ENGINEERING_PROJECT_DAG.json` 必须表达以下有向图：

```text
START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
  -> [HUMAN: AUTHORING_APPROVAL]
  -> SHARED_CONTROL_BASELINE_LOCKED
  -> CONTROL_PLANE_REGISTRATION
  -> PROGRAM_DRIVER_RUNTIME_VERIFIED
  -> LAB_BOOTSTRAP
  -> LAB_SELF_CONFORMANCE_PASS
  -> LAB_TOOL_RELEASE_LOCKED
  -> LINKAGE_BOOTSTRAP
  -> LINKAGE_SELF_CONFORMANCE_PASS
  -> LINKAGE_TOOL_RELEASE_LOCKED
  -> MAIN_EXECUTION_PACKAGE_MATERIALIZED
  -> MAIN_EXECUTION_PACKAGE_VALIDATED
  -> MAIN_PROGRAM_REGISTRATION
  -> G0/C0
  -> P1/C1
  -> P2/C2
  -> P3/C3 or approved P3_NA/C3
  -> P4_LOCAL_CLOSURE
  -> RELEASE_PIPELINE
```

固定顺序不是目录编号建议。缺少任何前驱 Lock、工具发布 Hash、自校验证据或兼容矩阵绑定时，下游节点不可激活。

## 4. 建设节点契约

| 节点 | 唯一 Owner | 必需前驱 | 必需成功输出 | 失败返回 |
| --- | --- | --- | --- | --- |
| `CONTROL_PLANE_REGISTRATION` | Program Control | Human Approval + Shared Baseline | 只读注册 Receipt；不执行工程 Workpack | Authoring/Registration 修复 |
| `PROGRAM_DRIVER_RUNTIME_VERIFIED` | Program Control Validator | Control Plane Registration | Driver 入口、版本、权限、Ledger/lease/idempotency 能力证明 | Driver bootstrap 修复或人工阻断 |
| `LAB_BOOTSTRAP` | Lab Build Workpack | Shared Baseline + verified Driver | 独立源码/测试/Schema/CLI 入口 | Lab Repair Workpack |
| `LAB_SELF_CONFORMANCE_PASS` | Lab 的独立 self-test authority | Lab Bootstrap Result | 正/负/篡改、自身来源和签发边界证据 | Lab Bootstrap/Repair |
| `LAB_TOOL_RELEASE_LOCKED` | Lab Release Gate | Self-conformance PASS | immutable Lab distribution hash/version | Lab Build/Release |
| `LINKAGE_BOOTSTRAP` | Linkage Build Workpack | Lab Tool Release + Shared Baseline | 只读 parser/report/CLI | Linkage Repair Workpack |
| `LINKAGE_SELF_CONFORMANCE_PASS` | Linkage self-test authority | Linkage Bootstrap Result | read-only、无修复、无发证的负向证据 | Linkage Bootstrap/Repair |
| `LINKAGE_TOOL_RELEASE_LOCKED` | Linkage Release Gate | Linkage self-conformance PASS | immutable Linkage distribution hash/version | Linkage Build/Release |
| `MAIN_EXECUTION_PACKAGE_MATERIALIZED` | Main Program Author/Workpack | 两个工具 Release Lock | Main-specific Charter/Phase/Workpack/Command/Pack 计划 | Main package authoring repair |
| `MAIN_EXECUTION_PACKAGE_VALIDATED` | Start Package Validator | Main Package Result | 结构、意图、DAG、授权、负向测试计划 PASS | Main package authoring repair |
| `MAIN_PROGRAM_REGISTRATION` | Build Program Driver | 人工批准范围 + validated package | target-root registration receipt；零 Workpack 执行 | Registration repair |
| `G0..P4` | Main Driver + 对应 Gate | 当前阶段前驱/C0-C3 | 当前 Phase Lock/Checkpoint | 最早失效 Phase |

Lab 和 Linkage 的“自校验”不能由其普通 happy-path 单测代替。至少必须证明：Lab 不接受伪 Codex receipt 或旧 nonce；Linkage 无写权限、不能修 Pack、不能签 Certificate。

## 5. 每个 DAG 节点的机器字段

`ENGINEERING_PROJECT_DAG.json` 中每个节点至少包含：

```text
node_id / project_id / node_kind / owner_role
required_predecessor_nodes / required_lock_refs
required_input_hashes / required_tool_distribution_hashes
required_execution_mode / required_authorization_scope
workpack_id or pipeline_action_id
allowed_read_paths / allowed_write_paths / environment_id
success_gate / success_output_refs / failure_return_node
invalidates_on / allowed_next_nodes / human_gate
```

所有边必须显式列出。Driver 不得根据 Markdown 标题、文件出现顺序或“通常下一步”创建隐式边。

## 6. 全局单 Workpack 对三工程的约束

工程建设 Workpack 按 DAG 串行激活。Lab、Linkage、Main 不能同时拥有 Active Workpack；一个工程失败后，不得先做另一个工程并承诺以后补修。

允许并行的仅是：

- 对同一 immutable snapshot 的只读静态检查；
- 不产生权威 PASS、Promotion 或修复的辅助分析；
- DAG 明确标注 `parallel_read_only_group` 且最终由一个串行 Gate 聚合的动作。

任一并行检查改变文件、环境、Lock 或 report verdict，都视为写 Workpack 并违反全局单 Active Workpack。

## 7. Main 阶段不可跳序

Main Program 注册成功不激活 P1。固定链为：

```text
PROGRAM_CHARTER_LOCK
-> G0 + C0 + G0_CONTROL_LOCK
-> P1 local closure + C1 + P1_BUILD_LOCK
-> P2 local closure + C2 + P2_BUILD_LOCK
-> P3 local closure/N/A decision + C3
-> P3_BUILD_LOCK or P3_NOT_APPLICABLE_LOCK
-> P4 local closure + P4_BUILD_INPUT_LOCK
```

P3 N/A 是人工批准的显式分支，不是自动 shortcut。没有当前 P2 Hash、C3 和 `P3_NOT_APPLICABLE_LOCK` 时，P4 始终不可选择。

## 8. P4 后唯一发布链

`RELEASE_PIPELINE_MANIFEST.json` 必须逐节点表达：

```text
P4_BUILD_INPUT_LOCK
-> PACK_DRAFT
-> LINKAGE_A_INTERFACE_COMPLETENESS
-> LINKAGE_B0_NORMATIVE_BINDING
-> LINKAGE_C_EVIDENCE_COMPATIBILITY
-> IMMUTABLE_ARTIFACT_BUILD
-> LINKAGE_B1_ARTIFACT_BINDING
-> P4_INSTALLABILITY_ENV_CREATE
-> EXACT_ARTIFACT_INSTALL_AND_ORIGIN_CHECK
-> P4_INSTALLABILITY_RECEIPT
-> P4_RELEASE_CANDIDATE_LOCK
-> SINGLE_CERTIFICATION_ENV_CREATE
-> CERTIFICATION_INSTALL_ONCE
-> INSTALLED_TARGET_DESCRIPTOR
-> LINKAGE_D_INSTALLED_HANDSHAKE
-> LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS
-> C4_REPORT
-> CONFORMANCE_CERTIFICATE
-> P4_CERTIFIED_RELEASE_LOCK
-> [HUMAN: REAL_TARGET_INSTALL_AUTHORIZATION]
-> REAL_TARGET_INSTALL
-> REAL_TARGET_INSTALLATION_RECEIPT
-> ACTIVE_INSTANCE_MANIFEST
```

自动化可以在有效 `EXECUTION_AUTHORIZATION.json` 下执行构建、P4 临时安装、唯一认证环境安装、D 和 C4；它不能跨越真实目标安装人工门禁。

## 9. 发布节点的项目责任

| 范围 | Main | Linkage | Lab | Certification Installer |
| --- | --- | --- | --- | --- |
| Pack Draft、Artifact | 生成并绑定输入 | 只读检查 | 读取计划 | 不修改 |
| A/B0/C/B1/D | 提供被审查资产 | 唯一 report owner | 消费相关绑定 | D 前提供安装描述 |
| P4/Certification install | 提供 immutable Artifact | 只读 | 不安装 | 唯一环境/安装 Owner |
| C4/Certificate | 提供 runtime evidence | 提供 D report | 唯一 verdict/certificate owner | 不判断 PASS |
| Real target | 提供 certified Artifact | 可只读核对 | Certificate 保持不变 | 获人工授权后唯一安装 Owner |

任何角色越权产生的输出必须标记 `AUTHORITY_MISMATCH`，不得被后继节点消费。

## 10. 工具与 Candidate 一致性

一次 Release/Certification Attempt 必须固定：

```text
shared baseline hash
Lab distribution hash/version
Linkage distribution hash/version
Main P4 Build Input Lock hash
Pack B0/B1 hashes
Artifact hash/version
Candidate Lock hash
environment and scenario-set identities
```

Lab/Linkage 工具变化不得在进行中的 Attempt 原地替换。变化影响判断时，终止 Attempt，失效相关计划/结果，并从 `REENTRY_PLAN.json` 指定的最早节点重新进入。

## 11. Finding、修复与重入边

DAG 必须包含失败边，而不是只有 happy path：

```text
failed node
-> structured Finding
-> earliest_invalid_node
-> exactly one repair_owner/project
-> downstream invalidation
-> bounded Repair Workpack
-> rebuild/reinstall/recertify from REENTRY_PLAN
```

典型路由：

- Main emitter、Pack、Artifact、入口错误 → Main Repair Workpack；
- Lab checker、attestation 或 certificate issuer 错误 → Lab Repair + 新 Lab Tool Release；
- Linkage parser/report 或 read-only 边界错误 → Linkage Repair + 新 Linkage Tool Release；
- Shared Protocol、Charter 或权威冲突 → Human Gate，重建 Shared Baseline。

Lab/Linkage Finding 不能直接修改 Main，Main 也不能放宽 Checker。修复后必须重新验证所有被复用上游 Hash。

## 12. 自动调度终态

Driver 只允许报告以下精确终态：

| 状态 | 含义 |
| --- | --- |
| `THREE_PROJECT_ENGINEERING_READY` | Lab、Linkage 工具已锁定，Main Program 已合法注册；未表示 Harness 完成 |
| `P4_BUILD_INPUT_READY` | Main P4 本地闭合，可进入发布链 |
| `RELEASE_CANDIDATE_READY` | Artifact/B1/Installability 完成；未认证、不可真实安装 |
| `CERTIFIED_RELEASE_READY` | C4/Certificate/Certified Lock 完成；尚未真实安装 |
| `WAITING_REAL_TARGET_INSTALL_AUTHORIZATION` | 人工硬门禁，正常停止 |
| `REAL_TARGET_ACTIVE` | 本次授权目标的安装 receipt 与 active manifest 已 readback |

任一工程只生成骨架、仅运行单测或只创建目录时，只能报告相应节点 `TOUCHED`，不得提升为以上终态。

## 13. 必需负向验证

自动 DAG 至少拒绝：

- Lab 未发布即搭建或运行 Linkage 权威审查；
- Linkage 未发布即注册 Main；
- 三工程出现两个 Active Workpack；
- Main 跳过 P3 或用空目录表示 N/A；
- B0 预填 Artifact Hash、B1 先于 Artifact；
- P4、认证与 Lab 使用不同 Candidate；
- Linkage 修复被审查资产或签发 Certificate；
- Lab/Linkage 工具中途换版却复用旧结果；
- Candidate Lock 被用于真实目标安装；
- 没有本次 `REAL_TARGET_INSTALL_AUTHORIZATION.json` 自动越过最终 Gate。
