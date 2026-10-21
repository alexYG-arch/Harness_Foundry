# 10｜失败回流、单一修复 Owner 与失效传播

> 状态：目标 Start 执行包的修复协议模板，不是已部署的修复系统。生成者必须把本协议实例化为目标工程的 Workpack、状态文件、失效图和校验命令；不得因本文存在就声称联通或修复能力已完成。

## 1. 核心原则

每个 finding 必须满足：

```text
一个 finding
→ 一个最早失效的权威节点
→ 一个 repair_owner
→ 一个 repair_workpack
→ 明确的 downstream invalidation set
→ 重建 / 重装 / 重新认证路径
```

禁止多个工程同时“顺手修复”同一问题。后果出现在哪里，不等于根因 owner 在哪里。

## 2. Finding 最低结构

目标包必须定义机器可读 schema，至少包含：

```json
{
  "finding_id": "F-<stable-id>",
  "detected_by": "LINKAGE|EXTERNAL_LAB|MAIN_BUILD_VALIDATOR",
  "failed_gate": "C0|C1|C2|C3|C4|A|B0|C|B1|P4_INSTALLABILITY|D",
  "error_code": "<closed-enum-or-versioned-code>",
  "earliest_invalid_node": "<artifact-or-contract-id>",
  "evidence_refs": [],
  "affected_intent_atom_ids": [],
  "repair_owner": "MAIN_BUILD|EXTERNAL_LAB|LINKAGE_TOOL|DESIGN_AUTHORITY",
  "repair_workpack_id": "WP-...",
  "invalidation_set": [],
  "required_reentry_gate": "C0|C1|C2|C3|C4|A|B0|C|B1|P4_INSTALLABILITY|D",
  "status": "OPEN"
}
```

`repair_owner` 必须且只能有一个。协助者可以列入 `consulted_parties`，但不能成为第二 owner。

## 3. Owner 路由

| 最早失效节点 | 唯一 Owner | 典型修复 |
|---|---|---|
| Canonical Source 冲突、需求语义不明确 | `DESIGN_AUTHORITY` | 用户/Human Gate 决策并重建 baseline |
| Atom 漏失、Workpack/阶段/Run Path/Pack 声明错误 | `MAIN_BUILD` | 修正文档或生成逻辑，重做受影响阶段 |
| Harness runtime、emitter、Artifact、安装入口错误 | `MAIN_BUILD` | 修代码、重建 Artifact、重新安装 |
| Lab checker、runner、attestation、Certificate issuer 错误 | `EXTERNAL_LAB` | 修 Lab distribution，提升 checker 版本并重认证 |
| Linkage 自身解析或 report 逻辑错误 | `LINKAGE_TOOL` | 修 Linkage 工具并重跑相关只读门禁 |

补充规则：

1. Pack 数据由 Main Build 的 Pack Workpack 修复；Pack parser/checker 属于 External Lab 时由 Lab 修复。
2. Linkage 发现问题只能开 finding，不得修改被审查对象。
3. Lab 发现 Harness 缺 receipt 时，owner 是 Main Build；不得让 Lab 放宽 checker。
4. Main Build 认为 checker 错误时必须提供可复现 finding；在 Lab 修复并发布新 Hash 前不得自行覆盖。

## 4. 失效图

目标包必须生成显式 DAG，而不是靠自然语言推断：

```text
Canonical Source / Intent Baseline
  → Charter / Requirements / Atom Coverage
  → Workpack DAG / StageSpec / Run Path / Receipt Matrix
  → Phase Locks and C0-C3 checkpoints
  → P4_BUILD_INPUT_LOCK
  → Pack B0 Binding
  → Evidence Compatibility C
  → Artifact
  → Pack B1 Binding
  → P4 Installability Receipt
  → P4_RELEASE_CANDIDATE_LOCK
  → Certification Installation Receipt / Installed Target Descriptor
  → D Handshake
  → External Lab C4 Evidence / Certificate
  → P4_CERTIFIED_RELEASE_LOCK / Active Instance
```

任何上游内容 Hash 变化时，所有依赖该 Hash 的下游节点必须变为 `STALE` 或 `REVOKED`，不能继续显示 PASS。

## 5. 强制失效规则

### 5.1 Canonical Intent 变化

必须失效：相关 Atom、coverage、Charter/requirement 映射、owner Workpack、受影响阶段 Lock/C0-C4 checkpoint、`P4_BUILD_INPUT_LOCK`、Pack B0/B1、Artifact、Candidate、安装证据、D、Certificate 和 Certified Release Lock。

如果影响分析能证明某个早期阶段与变化无依赖，它可以保留，但必须由机器依赖图给出证明，不能凭维护者口头判断。

### 5.2 阶段或前驱 Lock 变化

- P1 变化：P1 及全部下游失效；
- P2 变化：P2 及全部下游失效；
- P3 变化或缺失：P3/C3、P4、`P4_BUILD_INPUT_LOCK`、Artifact、Candidate、安装、D、C4 全部失效；
- `P4_BUILD_INPUT_LOCK` 变化：Artifact 及其下游全部失效；
- `P4_RELEASE_CANDIDATE_LOCK` 变化：唯一认证环境、D、C4、Certificate 和 Certified Lock 全部失效。

P3 即便声明不适用，也必须有获批且绑定当前前驱 Hash 的 `P3_NOT_APPLICABLE_LOCK`。无此 Lock 不能进入 P4。

### 5.3 Pack 或 Artifact 变化

- Pack 的规范绑定变化：从 B0 重新进入；
- Artifact 内容或 build provenance 变化：B1、P4 Installability、Candidate、认证安装、D、C4、Certificate 失效；
- 仅重新打包但 Hash 改变：仍视为新 Artifact，不能复用旧安装证据或 Certificate。

### 5.4 安装来源变化或源码回退

出现 editable install、`PYTHONPATH` 注入、PATH shadow、import realpath 指向源码/执行包、runtime root 为 Build Driver 时，必须使对应 Installation Receipt、Candidate（若其绑定该来源证据）、D、C4 和 Certificate 失效，并从适用的干净安装环境重新进入。

### 5.5 Checker、Attestation 或 Lab 环境变化

Checker implementation、规则集、distribution Hash、attestation 机制或有判断影响的 Lab 环境发生变化时：

- 旧 Certificate 不得与新 checker 组合使用；
- C4 结果和 `P4_CERTIFIED_RELEASE_LOCK` 必须失效；
- 至少从 C4 重新执行；
- 若 schema/兼容契约也变化，则必须从 Gate C 重新执行。

只改展示文案且可由 Hash/影响分析证明不影响判断时，可以保留 Certificate，但必须生成独立 non-semantic change receipt。

## 6. 修复状态机

```text
DETECTED
→ TRIAGED
→ OWNER_ASSIGNED
→ DOWNSTREAM_INVALIDATED
→ REPAIR_IN_PROGRESS
→ REPAIRED_LOCALLY
→ REBUILT
→ REINSTALLED
→ RECERTIFIED
→ CLOSED
```

不是所有 finding 都从 `REPAIRED_LOCALLY` 经过构建和安装；但凡影响 Main Harness Artifact、Pack binding、安装来源、runtime evidence 或 checker 判断，就必须经过相应的 `REBUILT`、`REINSTALLED`、`RECERTIFIED`。

禁止：

- 在未先标记下游失效时关闭 finding；
- 修改 report、receipt、Lock 或 Certificate 让其“重新匹配”；
- 只重跑失败命令但不重建已变化 Artifact；
- 在旧环境覆盖安装后沿用旧 installation receipt；
- 用 `WAIVED` 绕过安全、来源、阶段顺序、意图保真或 attestation 错误。

## 7. 唯一重入路径

联通与认证顺序固定为：

```text
P4 local closure → P4_BUILD_INPUT_LOCK → Pack Draft
→ A → B0 → C → Artifact Build → B1
→ P4 Installability → P4_RELEASE_CANDIDATE_LOCK
→ Single Certification Environment Install → D
→ Lab Installed Certification + C4 → Certificate → P4_CERTIFIED_RELEASE_LOCK
```

修复后从“最早可能受影响的门禁”重入：

| 修复范围 | 最早重入点 |
|---|---|
| canonical interface / phase model | A |
| Pack normative binding | B0 |
| schema、fixture、emitter/checker compatibility | C |
| Artifact 或 build provenance | B1 前先重建 Artifact |
| P4 可安装性、入口或来源 | P4 Installability |
| Candidate 或认证环境安装 | Single Certification Environment Install |
| 仅 External Lab scenario execution，且上游 Hash 全未变 | C4 |

重入时必须重新校验仍被复用的上游 Hash；发现 stale lock 时继续向上回溯，不能强行停在表中建议点。

## 8. Certificate 与活动实例

Certificate 至少绑定：

```text
canonical_intent_baseline_hash
charter/protocol_hash
pack_hash
artifact_hash
installation_descriptor_hash
checker_distribution_hash
attestation_policy_hash
scenario_set_hash
evidence_root_hash
issued_at / expires_at
```

失效事件必须进入 append-only invalidation/revocation ledger。活动实例读取到 Certificate、Artifact 或 installed descriptor 不匹配时，必须降级为 `CERTIFICATION_INVALID`，不得继续宣称 certified。

## 9. 验收要求

生成的目标 Start 包必须包含：

- finding schema 与封闭错误码策略；
- owner routing 表和每类 repair Workpack；
- 可机读 invalidation DAG；
- `STALE/REVOKED` 传播器的实现任务与测试；
- rebuild、clean reinstall、recertify 指令；
- checker 变化、P3 skip、stale lock 和源码回退的负向场景。

相关测试见[验收与负向测试](11_acceptance_and_negative_tests.md)。本文只规定应生成和实现什么，不构成运行证据。

## 10. 自动修复循环的执行边界

Driver 只能自动创建和执行已经由 `REPAIR_ROUTING_RULES` 唯一归属、且写路径/模式位于当前授权内的 Repair Workpack。每轮必须更新 `LOOP_STATE`：

- attempt/round 与最大预算；
- Finding fingerprint 与重复次数；
- 本轮输入、Diff、Evidence 和 invalidation Hash；
- 是否产生可测量进展；
- 下一重入点、stop reason 和 escalation owner。

相同 Finding 无进展重复、两个状态往返、重入点持续上移、repair owner 不唯一或需要改变 Canonical Intent 时，状态必须进入 `LOOP_ESCALATED` 并停止。Human 处理后只能凭新的 resume authorization 继续，旧 loop budget 不得静默重置。

机器状态、崩溃恢复和幂等要求见[Program Driver、Loop 与恢复](15_program_driver_loop_and_recovery.md)。
