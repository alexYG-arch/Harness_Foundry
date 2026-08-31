# Harness Foundry v3.0 后续智能架构与规模化治理提案

> 历史状态：`HISTORICAL_NON_NORMATIVE_ARCHIVE`
>
> 本文件保存人工成本控制重构前的R0完整提案，仅用于回溯；当前规范入口为`HARNESS_FOUNDRY_V3_0_FOLLOW_ON_ARCHITECTURE_PLAN.md`。除本归档说明外，以下正文与重构前文件一致。

## 0. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | `FUTURE_PROPOSAL_NOT_V2_9_GATE` |
| 前置版本 | Harness Foundry v2.9 Certified Release |
| 目标版本 | Harness Foundry v3.0 |
| 编写日期 | 2026-08-03 |
| 来源 | v2.9 R7范围纠偏后迁出的高级能力 |
| v2.9入口 | `HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN.md` |
| R7完整快照 | `HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN_R7_PRE_3_0_SPLIT_ARCHIVE.md` |
| 来源案例 | `HARNESS_FOUNDRY_V2_9_SOURCE_CASE_001.md`，仅作非规范输入 |
| 非授权声明 | 本文不授权实现、迁移、执行、安装、认证、发布或Git操作 |

## 1. 为什么需要独立v3.0

v2.9负责关闭最小可信执行闭环：

```text
意图和需求锁定
→ 生产架构锁定
→ 宪章执行
→ 风险授权
→ 自动推进
→ 可恢复执行
→ 按需证据
→ 可移植闭环
```

R7曾把大量平台化和研究型能力同时加入v2.9，造成36项目标、25个Gate、35个CLI入口、67类制品和44项发布验收。它们并非无价值，但会让v2.9重新出现人工门过多、链路过长、预算STOP和大爆炸式重构。

v3.0承接的问题不同：

> 当v2.9最小闭环已经稳定后，如何把它扩展为能够跨项目、跨控制域、跨设备和跨组织持续学习、优化和认证的平台。

因此v3.0是后续增强，不是v2.9完成条件。

## 2. 进入v3.0的硬前提

只有全部满足后才能启动v3.0：

1. v2.9 P0-01至P0-10已经实现并有Runtime Evidence；
2. Authoring和Runtime的自动推进在真实项目中通过；
3. 用户无需手工输入子Hash；
4. 全部规范性Charter Clause处置和执行闭环通过；
5. Checkpoint/Resume在预算和进程中断场景通过；
6. 至少一个非来源Target Profile证明Core不受案例污染；
7. v2.8和v2.9都有独立Certified Release Lock；
8. v3.0使用新的Program、State、Output、Authorization和Certificate链。

如果任一前提未满足，应回到v2.9修复，不得用v3.0能力绕过。

## 3. v3.0目标能力

| ID | 能力 | 价值 |
|---|---|---|
| `V3-01` | Adaptive Expert Intent Engine | 更少问题获得更高歧义消除和返工避免 |
| `V3-02` | Architecture Synthesis and Topology Optimizer | 自动比较多种Harness架构和风险/成本 |
| `V3-03` | Advanced Policy Formalization | 处理复杂自然语言Policy、冲突和证明 |
| `V3-04` | Distributed Durable Orchestration | 跨主机、长周期、多任务恢复与协调 |
| `V3-05` | Adaptive Review and Cost Router | 按风险、分歧和成本动态选Validator/模型/人工 |
| `V3-06` | External Certification Network | 支持L4外部组织、Provider和Signer |
| `V3-07` | Supply-chain and Protocol Portability | OCI、SBOM、SLSA、in-toto、MCP/A2A |
| `V3-08` | Platform Evolution Governance | Case-to-Core晋升、Canary矩阵和兼容演化 |
| `V3-09` | Cross-program Observability | 跨Program质量、成本、漂移和恢复分析 |
| `V3-10` | Policy and Architecture Learning Loop | 从历史Finding提议候选规则，但不自动升权 |

## 4. 总体架构

```text
v2.9 Trusted Execution Core
  ├─ Requirement / Architecture / Charter Locks
  ├─ Risk Authorization and Auto Progress
  ├─ Checkpoint / Resume
  └─ Evidence / Independent Closure
        ↓ stable extension APIs
v3.0 Adaptive Control Plane
  ├─ Intent Intelligence
  ├─ Architecture Synthesis
  ├─ Policy Formalization
  ├─ Distributed Orchestration
  ├─ Adaptive Review and Cost Routing
  ├─ External Certification
  ├─ Supply-chain / Protocol Federation
  └─ Evolution and Observability
```

v3.0只能调用v2.9冻结的Extension API，不能重新定义v2.9的授权、状态、Clause处置和Claim Closure语义。

## 5. Adaptive Expert Intent Engine

### 5.1 目标

在v2.9“最多三个高价值问题”的基础上，增加：

- Intent Hypothesis Set的概率或置信度维护；
- EVPI、风险、返工成本和打断成本联合排序；
- 根据用户经验动态调整问题粒度；
- 从历史项目提取反例候选；
- 跨轮次Decision Delta和冲突传播；
- 不同Architecture Candidate对问题价值的反馈。

### 5.2 边界

- 不把用户未纠正的假设升级为事实；
- 不输出或要求隐藏Chain-of-Thought；
- 只输出可审核的假设、证据、取舍、问题和Decision Record；
- 低风险问题可以延后，但高关键冲突不能由概率覆盖；
- 所有学习结果只形成候选，不直接改变冻结Requirement。

### 5.3 验收方向

- 与固定问题集相比，Blocking歧义关闭率不降低；
- 人工轮次和返工率下降；
- 高关键问题召回率可测；
- 对错误历史案例的迁移不会污染新Target；
- 用户可以查看为何当前问题优先，而无需查看模型隐藏推理。

## 6. Architecture Synthesis and Topology Optimizer

v2.9只要求发现缺口、提出有限候选并由用户Lock。v3.0增加：

1. 从Capability/Behavior/State自动生成多种Architecture Candidate；
2. 比较Stage、Module、Subharness和Semantic Slot的替代拓扑；
3. 估计控制流复杂度、恢复面、共同失效、成本和延迟；
4. 进行Architecture Counterexample和故障注入；
5. 识别可删除、合并或参数化的节点；
6. 在多个Target Profile之间验证拓扑通用性；
7. 生成`CONTROL_FLOW_DELTA`和演化影响。

Optimizer不能自行批准Architecture Lock。它只能提交：

```text
Candidate
+ Assumptions
+ Tradeoffs
+ Evidence
+ Unresolved Decisions
+ Migration Impact
```

## 7. Advanced Policy Formalization

v2.9保留全量Clause处置和确定性执行；v3.0研究并实现：

- 自然语言Clause到形式Policy的多候选编译；
- Policy语义等价检查和反例生成；
- 多Policy Bundle冲突求解；
- Temporal Policy、跨阶段Policy和外部法规绑定；
- Policy作者、测试者、执行者和Signer分离；
- Policy变更影响和最小失效子图；
- 外部Policy Engine和透明Decision Log；
- Policy自动形式化的置信度与人工批准路由。

任何自动形式化输出在批准前均为`POLICY_CANDIDATE`，不能成为Authorization Source。

## 8. Distributed Durable Orchestration

v2.9只要求单Program可靠恢复。v3.0可增加：

- 多主机Event Store复制；
- Lease、Heartbeat和Worker故障转移；
- 跨Program依赖和Saga补偿；
- 外部Activity的长周期Reconciliation；
- 跨控制域Signal/Update；
- 分布式幂等键和Exactly-once Claim边界；
- 长任务的分片Checkpoint；
- 多任务资源和成本预算协调；
- 人工等待期间的授权/环境漂移监控。

分布式能力不能弱化v2.9的单一权威状态、Hash绑定、授权过期和未知副作用Fail-closed。

## 9. Adaptive Review and Cost Router

### 9.1 输入信号

```text
risk_delta
+ irreversibility
+ policy_unknown
+ intent_uncertainty
+ validator_disagreement
+ common_mode_risk
+ expected_information_gain
+ latency_and_cost
```

### 9.2 可选路由

- deterministic check；
- lightweight model/tool；
- stronger model；
- second independent implementation；
- heterogeneous Provider；
- internal human；
- external certifier。

### 9.3 防止成本反噬

- 先确定性后语义；
- 只有风险和分歧证明升级有价值时才增加昂贵Oracle；
- 预算达到上限提交Checkpoint，不以“还差一点”无限延长；
- Router的成本预测和真实消耗必须回读；
- Router不能降低v2.9硬性Policy或Evidence义务。

## 10. External Certification Network

v3.0扩展独立性等级：

| 等级 | 条件 |
|---|---|
| `L2_COORDINATED` | 独立上下文/workspace/state，但可能模型和实现同源 |
| `L3_INTERNAL_AUTHORITY` | 独立顶层任务、Credential、Signer、Validator和发布权 |
| `L4_EXTERNAL` | 外部组织、Provider、基础设施或人工审计机构 |

v3.0需要：

- 外部Task Envelope和不可变Artifact Exchange；
- 独立Fixture、Oracle和Signer登记；
- 相关错误风险评估；
- 多Oracle的`ALL_OF / QUORUM / DISAGREEMENT_STOP`；
- Certificate中记录独立性向量和残余共同失效；
- 外部结果不可被父Orchestrator改写或选择性丢弃。

不同模型、不同Prompt或复制Validator仍不能单独证明独立。

## 11. Supply-chain and Protocol Portability

v3.0在v2.9 clean-clone基础上增加：

- SBOM与依赖透明；
- SLSA构建等级和Provenance；
- in-toto布局和步骤证明；
- OCI镜像/Artifact身份；
- 可验证构建和透明日志；
- 跨OS/架构发布矩阵；
- MCP Resource URI、Tool Schema和Server Capability协商；
- A2A Task、Message和Artifact交接；
- 插件发现、版本、权限和Secret Scope；
- 离线、降级和Provider替换合同。

容器、GitHub上传或协议兼容本身都不等于可信认证，仍需v2.9授权、执行、证据和Claim Closure。

## 12. Platform Evolution Governance

### 12.1 Case-to-Core Promotion

案例Finding必须先分类：

- `PLATFORM_INVARIANT_DEFECT`；
- `PROFILE_VARIATION`；
- `IMPLEMENTATION_DEFECT`；
- `FIXTURE_OR_ORACLE_DEFECT`；
- `NO_CHANGE_REQUIRED`。

进入Core的候选至少满足：

- 领域无关不变量可形式化；
- 或在两个非来源、互不相似Profile独立复现；
- 或属于显式批准的安全/权限例外。

### 12.2 Canary Property Matrix

Canary按性质而非故事组织：

- structural identity；
- deterministic runtime behavior；
- semantic structured output；
- generative portfolio；
- permission and denial；
- migration and compatibility；
- portability；
- recovery；
- common-mode failure。

### 12.3 演化合同

每次Core变化输出：

- Extension API Delta；
- Control Flow Delta；
- State/Schema Migration；
- Profile Compatibility；
- Case Ablation；
- Cost/Latency Delta；
- Rollback Plan；
- Deprecated Path Removal。

## 13. Cross-program Observability

v3.0可以建立跨Program只读分析面：

- Requirement到生产路径缺口率；
- Charter Clause执行与Unknown率；
- 自动推进距离和人工门原因；
- Checkpoint恢复成功率；
- Validator分歧和共同失效；
- Evidence体积、重复率和Hash复用；
- 模型/工具成本与升级收益；
- Profile和Core演化影响；
- Release与回滚质量。

Observability不得成为新的权威状态库，不得修改Program结果或替代独立证据。

## 14. v3.0制品和入口原则

v3.0仍应优先使用Bundle和组合入口，避免重建R7的67类操作者制品与35个CLI入口。

建议逻辑Bundle：

- `INTENT_INTELLIGENCE_BUNDLE`；
- `ARCHITECTURE_SYNTHESIS_BUNDLE`；
- `POLICY_FORMALIZATION_BUNDLE`；
- `DISTRIBUTED_ORCHESTRATION_BUNDLE`；
- `REVIEW_COST_ROUTING_BUNDLE`；
- `EXTERNAL_CERTIFICATION_BUNDLE`；
- `SUPPLY_CHAIN_PROTOCOL_BUNDLE`；
- `EVOLUTION_OBSERVABILITY_BUNDLE`。

每个Bundle内部可有机器制品，但默认只暴露：

```text
v3 plan
v3 advance-until-gate
v3 explain-decision
v3 inspect-evidence
v3 resume
```

新增CLI必须证明不能由组合入口或`--detail`承载。

## 15. v3.0发布验收方向

v3.0发布前至少证明：

1. 不改变v2.9 P0 Gate、授权和Claim语义；
2. 所有高级能力可以关闭而不影响v2.9运行；
3. Adaptive Intent降低人工轮次且不降低Blocking歧义召回；
4. Architecture Optimizer不会自动批准或扩大Scope；
5. Policy自动形式化不会绕过全量Clause处置和人工Freeze；
6. 分布式恢复不会重复非幂等副作用；
7. Review Router不会降低硬性Evidence/Policy要求；
8. L4外部结果具有独立Signer和不可变交接；
9. Supply-chain证明可跨设备和独立进程验证；
10. Case-to-Core Promotion能拒绝单案例直接升Core；
11. Observability保持只读且不成为第二权威状态；
12. 成本、延迟、证据体积和人工负担不高于声明预算；
13. v2.9 Compatibility和Rollback通过；
14. 所有研究性Claim与真实生产证据分开标注。

## 16. R7 Scope Migration Matrix

本矩阵覆盖R7全部40个顶层章节。`KEEP_2_9`表示保留在R8；`SPLIT`表示最小部分留在2.9、高级部分进入3.0；`MOVE_3_0`表示不再阻塞2.9；`ARCHIVE`表示仅保留历史或案例证据。

| R7章节 | 处置 | v2.9 R8去向 | v3.0去向 |
|---|---|---|---|
| 0 文档信息 | `KEEP_2_9` | R8元数据与边界 | 本文元数据 |
| 1 执行摘要 | `SPLIT` | 最小可信闭环 | 规模化智能控制面 |
| 2 当前能力与边界 | `KEEP_2_9` | v2.8→2.9差距 | v3进入条件 |
| 3 来源案例抽象 | `ARCHIVE` | 只保留Case不能改Core | SOURCE_CASE_001 |
| 4 通用根因 | `KEEP_2_9` | 生产、Policy、自动推进根因 | 跨Program演化分析 |
| 5 升级目标 | `SPLIT` | P0-01至P0-10 | V3-01至V3-10 |
| 6 目标架构 | `SPLIT` | 双锁、Policy、Auto Progress | Adaptive Control Plane |
| 7 Requirement类型 | `KEEP_2_9` | 按需分类 | 跨Profile分析 |
| 8 Evidence Obligation | `SPLIT` | 最低兼容性 | 多Oracle和成本优化 |
| 9 Independent Oracle | `SPLIT` | 内部独立最低要求 | L4外部Oracle网络 |
| 10 Runtime Topology | `SPLIT` | Profile声明、Core不固定 | Topology Optimizer |
| 11 Coverage Graph | `KEEP_2_9` | Requirement→Run→Evidence | 跨Program图分析 |
| 12 Factory门禁 | `SPLIT` | 合并为8个Gate | 高级Gate内部策略 |
| 13 状态机 | `SPLIT` | 精简Authoring/Runtime状态 | 分布式状态和Saga |
| 14 CLI升级 | `SPLIT` | 10个组合入口 | 5个v3组合入口 |
| 15 Finding类型 | `SPLIT` | P0 Finding | 演化、外部认证和优化Finding |
| 16 新增制品 | `SPLIT` | 8个逻辑Bundle | 8个高级Bundle |
| 17 正规执行 | `KEEP_2_9` | 风险授权、自动推进、恢复 | 跨域调度 |
| 18 Golden Canary | `SPLIT` | 最小Applicability Canary | Property Matrix |
| 19 测试策略 | `SPLIT` | P0单元/E2E | 高级对抗和跨域测试 |
| 20 迁移方案 | `KEEP_2_9` | v2.8隔离迁移 | v2.9→v3.0迁移 |
| 21 兼容策略 | `KEEP_2_9` | 不静默升级 | v3兼容/回滚 |
| 22 验收标准 | `SPLIT` | 18项P0验收 | 14项v3验收方向 |
| 23 风险与控制 | `SPLIT` | P0风险 | 平台规模化风险 |
| 24 回溯证据 | `ARCHIVE` | 非规范来源指针 | Evolution输入候选 |
| 25 实施顺序 | `SPLIT` | 12步P0 | v3阶段路线 |
| 26 最终原则 | `KEEP_2_9` | 最小可信闭环原则 | 不覆盖v2.9原则 |
| 27 关联文档影响 | `ARCHIVE` | R7历史快照 | 本矩阵替代 |
| 28 最新研究复核 | `MOVE_3_0` | 不作2.9 Gate | v3研究和实验依据 |
| 29 宪章/Review/预算 | `SPLIT` | 全量Clause、固定风险门、Resume | 自动形式化、Adaptive Router |
| 30 Expert Chat | `SPLIT` | 最多3个高价值问题 | EVPI、学习型提问和反例库 |
| 31 GitHub可发布 | `SPLIT` | clean clone与Manifest | SBOM/SLSA/OCI/MCP/A2A |
| 32 增加其他工程 | `SPLIT` | 不按数量增加工程 | Risk-driven物理拓扑优化 |
| 33 三CLI独立性 | `SPLIT` | L2/L3诚实声明 | L4外部网络 |
| 34 隔离启动 | `KEEP_2_9` | 新根、零回写 | v3独立新Epoch |
| 35 研究与规范来源 | `MOVE_3_0` | 仅保留必要原则 | 研究登记与实验计划 |
| 36 生产架构优先 | `KEEP_2_9` | Production-first Repair | 跨项目优化 |
| 37 Freeze后架构设计 | `SPLIT` | Architecture Lock与有限候选 | 自动综合和Optimizer |
| 38 同Chat独立 | `SPLIT` | 不伪称独立、L3内部认证 | L4外部认证 |
| 39 Profile交接 | `SPLIT` | Rule/Profile Freeze | 学习和晋升治理 |
| 40 案例去偏置 | `SPLIT` | Profile不改Core、Ablation | Case-to-Core Promotion和演化 |

### 16.1 覆盖结果

| 指标 | 结果 |
|---|---:|
| R7顶层章节 | 41 |
| 已映射章节 | 41 |
| 未映射章节 | 0 |
| 静默删除 | 0 |
| v2.9 P0保留或拆分 | 36 |
| 完全迁入v3.0 | 2 |
| 历史/案例归档 | 3 |

R7原始细节仍完整保存在R7历史快照；来源案例仍完整保存在SOURCE_CASE_001。迁移不代表对应能力已经实现。

## 17. v2.9与v3.0的强边界

| 问题 | v2.9回答 | v3.0回答 |
|---|---|---|
| 怎样少问但不漏关键需求 | 最多3个高价值问题 | 学习型EVPI与用户模型 |
| 怎样设计Harness | 有限候选+人工Architecture Lock | 自动综合和拓扑优化 |
| 怎样执行宪章 | 全量Clause+确定性Policy | 高级自动形式化和冲突证明 |
| 怎样不中断 | 单Program Checkpoint/Resume | 分布式多任务编排 |
| 怎样减少人工Review | 固定风险规则 | Adaptive Review Router |
| 怎样证明独立 | 内部L3 | 外部L4网络 |
| 怎样跨设备发布 | clean clone+Manifest | 完整供应链和协议联邦 |
| 怎样避免案例污染 | Profile不改Core+Ablation | 自动晋升和平台演化治理 |

任何v3.0实现不得被反向描述成v2.9已完成能力。

## 18. 建议阶段

```text
Phase 0  Verify v2.9 Certified Baseline
Phase 1  Intent and Architecture Intelligence Experiments
Phase 2  Advanced Policy Formalization
Phase 3  Distributed Orchestration
Phase 4  Adaptive Review and Cost Routing
Phase 5  External Certification and Supply-chain Federation
Phase 6  Evolution Governance and Observability
Phase 7  v3.0 Release Candidate and Rollback Validation
```

每个Phase独立授权、独立预算、独立证据；不得用创建v3.0文档授权实际执行。

## 19. 主要风险

| 风险 | 控制 |
|---|---|
| v3.0再次变成大爆炸 | 各能力可关闭、分Phase验收，不阻塞v2.9 |
| 自动架构覆盖用户决定 | Candidate-only，Architecture Lock仍需批准 |
| Policy自动形式化产生假等价 | 多候选、反例、独立测试和人工Freeze |
| 分布式状态形成多个真相 | v2.9权威Event语义不变，复制层不可改写历史 |
| Review Router为省钱降低质量 | 硬Evidence和Policy不可降级 |
| 多Provider仍相关错误 | 独立实现、确定性Oracle、权限和Signer优先 |
| 供应链制品爆炸 | 逻辑Bundle、Hash引用和分层回读 |
| 案例自动晋升污染Core | 多Profile复现、Ablation和Architecture批准 |
| Observability变成第二状态库 | 只读、可重建、不参与Promotion |
| 研究结论被写成已实现 | 区分`RESEARCH`、`EXPERIMENT`、`IMPLEMENTED`、`CERTIFIED` |

## 20. 研究和工程参考方向

以下只支持v3.0研究，不是实现或认证证据：

- [Agent Harness Engineering Survey](https://openreview.net/forum?id=eONq7FdiHa)：生命周期、上下文、工具和控制流的分层；
- [LLM-as-Code Agentic Programming](https://arxiv.org/abs/2606.15874)：确定性程序持有循环、分支和停止；
- [Correlated Errors in Large Language Models](https://arxiv.org/abs/2506.07962)：不同模型和Provider仍可能共享错误；
- [Temporal Durable Execution](https://temporal.io/)：Event、Activity、Signal、Heartbeat和恢复；
- [Open Policy Agent](https://www.openpolicyagent.org/docs)：Policy Decision与Enforcement参考；
- [SLSA](https://slsa.dev/)与[in-toto](https://in-toto.io/)：供应链身份、构建来源和步骤证明；
- [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)与[A2A Specification](https://a2aproject.github.io/A2A/latest/specification/)：Resource/Tool和Task/Artifact互操作。

采用任何研究结果前必须建立Target-specific实验、负向测试和成本边界。

## 21. 最终原则与非声明

```text
v2.9 closes the trustworthy loop.
v3.0 scales, learns and federates it.
No v3 feature may weaken v2.9 authority, authorization or evidence.
Advanced intelligence proposes; frozen policy and humans authorize.
Distributed execution must preserve one authoritative history.
More models, agents and projects do not automatically create independence.
Evolution is allowed only with traceable migration and rollback.
```

本文是`FUTURE_PROPOSAL_NOT_V2_9_GATE`。它不证明v3.0能力已实现，也不授权开始v3.0 Program、执行、迁移、发布或认证。
