# Harness Foundry v2.9 R7 拆分前历史快照

> 状态：`HISTORICAL_NON_NORMATIVE_ARCHIVE`
>
> 本文件保存将高级平台能力迁入v3.0前的完整R7。它只用于范围追踪、无损迁移核对和历史回溯，不是现行v2.9规范、实现授权或认证证据。现行v2.9入口仍为`HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN.md`。

---
# Harness Foundry v2.9 通用生产架构、可信执行与合规升级方案

## 0. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | `PROPOSAL` |
| 基线版本 | Harness Foundry v2.8 |
| 目标版本 | Harness Foundry v2.9 |
| 编写日期 | 2026-07-24 |
| 回溯修订日期 | 2026-07-25 |
| 授权交互优化修订日期 | 2026-08-01 |
| 研究、可移植性与隔离启动修订日期 | 2026-08-01 |
| 生产架构、控制流与隐性规则修订日期 | 2026-08-03 |
| 案例去偏置与链路增量控制修订日期 | 2026-08-03 |
| 案例物理拆分修订日期 | 2026-08-03 |
| 当前提案修订 | `PROPOSAL-R7` |
| 来源案例边界 | 案例已移至独立 `NON_NORMATIVE_SOURCE_CASE`；Core不读取案例标识、叙事或Fixture |
| 来源案例文件 | `HARNESS_FOUNDRY_V2_9_SOURCE_CASE_001.md` |
| R6历史快照 | `HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN_R6_CASE_HEAVY_ARCHIVE.md` |
| 目标 | 使 Foundry 不仅能证明需求、制品、接口和安装链一致，还能阻止缺少真实运行与独立语义证据的实现被错误认证 |
| 通用性边界 | 平台Schema、门禁、状态机、CLI、迁移和发布规则不得依赖任何Target产品、Provider、Artifact字段、固定数量、固定Topology、案例路径、本机绝对路径、同级私有仓库或未声明插件 |
| 证据口径 | 本次修订区分 `CURRENT_FACT`、`HISTORICAL_FACT`、`INFERENCE` 与 `V2_9_PROPOSAL`；提案不得被写成已实现能力 |
| 非授权声明 | 本文是升级设计，不授权修改 v2.8 规范、执行 Workpack、发布、认证、安装或 Git 操作 |

## 1. 执行摘要

Harness Foundry v2.8 已建立较完整的可信交付控制：

- 只读规范包与 Spec Hash 锁；
- SQLite 权威状态和事件链；
- Requirement IR 冻结、Readback、Freeze 和 Reopen；
- Intent Atom 到 Workpack、Stage、Release Step 和 Owner 的 `coverage_edges`；
- Main、External Lab、Linkage 的职责分离；
- Workpack、Command Manifest、Capsule、Result 和反向 Atom 绑定；
- Artifact、认证、安装和 Active Instance Manifest 的 Hash 贯通；
- 明确的人类授权门和自动执行边界。

来源案例复核表明，这些机制能够证明“正确的流程处理了同一个制品”，却不能天然证明“实现行为满足语义要求”。如果真实语义要求被实现为模板轮转，验证器又只检查数量、Schema、自报指标和 Hash，那么整个控制链仍可能形成形式正确、行为错误的绿色结果。

前一版提案把主要篇幅放在如何证明结果，容易形成“生产逻辑不变，只继续增加校验”的偏置。2026-08-03 复核确认：若 Producer 仍由模型自由决定分解、循环、工具、停止和降级路径，再强的 Validator 也只能更早发现错误，不能从源头减少错误。v2.9 必须先建立生产设计链：

```text
Frozen Intent
→ Capability and Behavior Decomposition
→ Architecture Decision IR
→ Stage / Subharness / Module Topology
→ Domain Rule and Governance Policy Compilation
→ Deterministic Run Contract
→ Bounded Semantic Execution
```

然后才进入证明链：

```text
Requirement Type
→ Evidence Obligation
→ Independent Oracle
→ Runtime Proof
→ Adversarial Proof
→ Certification Closure
```

语义 Requirement 不得再被结构、Hash、接口联通或安装证据单独关闭。

两条链的关系是：生产设计链回答“系统按什么逻辑运行”，证明链回答“如何证明它确实按该逻辑运行”。任何 Finding 若只增强 Validator、却没有确认 Producer 架构与规则是否已修复，均不得关闭为 `ROOT_CAUSE_RESOLVED`。

2026-08-01 的重新核对进一步确认：只增加 Start Package、执行包、校验工程和联通测试的数量，仍不能自动解决宪章执行不一致、共同失效、人工门过多、预算耗尽中断、长任务恢复和跨设备复现。v2.9 还必须把以下五项纳入同一个可执行闭环：

```text
Expert Intent Lock
→ Executable Charter Policy
→ Durable Event-sourced Orchestration
→ Independent Control Domains
→ Portable Release Contract
```

这里的“增加能力”不等于固定再增加若干仓库或若干 Agent。项目拓扑必须按风险 Profile 编译：低风险项目可把能力实现为同一发行物中的隔离模块；高风险认证路径才要求独立进程、独立任务上下文、独立权限、独立签名或独立实现。

通用性判定采用以下边界：

```text
Platform Core
  = domain-neutral schemas + gates + lifecycle + evidence compatibility

Target Profile
  = target-specific executors + topology + oracles + fixtures + thresholds

来源案例
  = one Target Profile and one Golden Canary
  ≠ Foundry v2.9 platform semantics
```

任何平台级规则若直接要求某个产品、Provider、Artifact字段、固定数量、固定Topology或案例专属Lane，均视为 `PLATFORM_DOMAIN_LITERAL_HARDCODED`，不得进入v2.9 Release。

但“声明案例不是平台规则”还不够。R6历史版让同一个来源案例同时承担触发证据、Schema/Oracle示例、Golden Canary、验收样本和候选生产拓扑，叙事权重过高，容易让设计者或模型围绕首个案例扩展Gate、Stage、Subharness、重试与转向策略。R7通过物理拆分落实案例去偏置边界：

```text
Normative Core
  ← 只能来自领域无关不变量或经跨领域复现的问题

Target Profile
  → 只能填写Core已经声明的扩展槽
  → 不能增加Core状态、Gate、CLI或控制流

Case / Fixture / Canary
  → 只能消费Profile并验证某项性质
  → 不能成为Core编译输入或运行时路由来源
```

实际 v2.9 规范包必须能够在不加载 source-case Profile、案例正文和 Fixture 的条件下编译、测试并解释完整 Core。案例可以发现问题，但不能单独决定平台向哪里升级。

### 1.1 给非技术读者的解释

可以把整个流程理解成“装修一栋重要建筑”：

- **人工授权**像业主决定“这次是否允许施工”，人负责判断风险和范围；
- **Hash**像材料和施工图的防拆封条码，机器负责逐项扫码，确认没有被偷偷调换；
- **Authorization Bundle**像一张封好的整车货物清单，里面仍有每件材料的条码，但业主只需要确认整车清单的一个总编号；
- **bounded automation**像只允许施工队在指定楼层、指定时间、指定预算内连续施工，走到拆承重墙、接入正式电网或交付使用时必须重新找业主。

因此，v2.9 的目标不是取消人工授权，也不是取消子项 Hash，而是把职责分开：

```text
人：看懂范围和风险，决定“做不做”
机器：验证全部文件、命令、状态和证据“是不是授权时那一份”
```

用户不应再复制几十个子 Hash。系统应展示可读摘要，并让用户只确认 `milestone_id + authorization_bundle_root_sha256` 或与其绑定的短挑战口令；Driver 仍必须在后台验证完整子 Hash 闭包。

## 2. 当前系统能力与边界

### 2.1 v2.8 已经解决的问题

v2.8 已能较好解决：

1. 需求来源是否被替换；
2. Requirement 是否被持久化而非只存在于聊天；
3. Atom 是否路由到对应 Workpack 和阶段；
4. Build、Lab、Linkage、Release 是否使用同一个 Artifact；
5. Bootstrap 是否被误当成执行授权；
6. Workpack、认证和安装是否越过人类授权边界；
7. 安装对象是否等于认证对象；
8. 历史证据是否被后续阶段改写。

### 2.2 v2.8 尚未充分机器化关闭的问题

现场回溯表明，v2.8 规范文本已经定义了 External Lab、受控 Runner、挑战 nonce、进程谱系、原始事件、独立证据源、正负向/篡改矩阵、Atom 到 Evidence 的双向覆盖，以及“文件存在不足以证明履约”等原则。因此，下列问题不能再表述为“v2.8 没有概念”，准确差距是：这些规范原则尚未全部成为 Requirement IR、Factory Freeze、Lab Oracle 和 Certificate Closure 的可执行硬门。

1. Requirement 属于结构、行为还是语义要求；
2. 哪些要求必须运行真实 Executor 才能关闭；
3. 哪些证据只是实现自报，不能作为独立证据；
4. External Lab 是否真正独立重新计算结果；
5. 语义输出是否由本次 Input 推理得到；
6. 多路推理的真实调用拓扑是否发生；
7. 输出差异是否来自内容，而不是编号、秒数或模板词替换；
8. Fake Launcher 是否被错误用于最终认证；
9. Linkage PASS 是否被误解为语义 PASS；
10. Hash 锁定的是正确实现，还是被锁定的错误实现。

### 2.3 v2.8 → v2.9 的真实增量

| 能力 | v2.8 规范状态 | 来源案例中的已观察状态 | v2.9 增量 |
|---|---|---|---|
| Runtime Receipt 与 Trusted Runner | 已有规范定义 | 有安装/运行回执，但产品语义 Executor 未形成 Atom 级证明 | 将进程、挑战、输入输出和模型绑定字段编译成强制 Evidence Obligation |
| External Lab 独立性 | 已有职责与独立证据原则 | Lab 项目独立，但业务语义检查仍采用结构/协议判定 | 要求从原始输出独立重算，并声明实现独立性 |
| Positive/Negative/Tamper | 已有矩阵规范 | 有用例声明和矩阵，但缺少近义改写、模板轮转等可执行语义 Oracle | 将用例绑定到 Oracle 版本、阈值、原始输入和预期 Finding |
| Intent Traceability | 已有 Atom、Acceptance Observation、双向覆盖原则 | Coverage 只路由至 Main G0，未路由到 Lab/Certification 关闭点 | 从“路由覆盖”升级为“履约覆盖” |
| Certificate/Linkage | 已有 Artifact 身份连续性 | v0.2 证书链完整，但语义 PASS 采信了弱不变量 | Certificate 必须绑定独立 Oracle 的原始重算结果 |

v2.9 的重点是**机器化、类型化、可执行化和 Fail-closed**，而不是重新命名 v2.8 已存在的治理概念。

## 3. 来源案例抽象与文档边界

### 3.1 Core只保留什么

来源案例已经物理迁移到`SOURCE_CASE_001`非规范文档。主提案只保留能够跨领域表达的问题类型：

1. Requirement声明了行为或语义目标，但没有原子化真实Executor与Runtime Topology；
2. Producer用结构唯一、自报指标或替代实现制造表面PASS；
3. Coverage只证明路由存在，没有绑定履约Evidence、Independent Oracle与Certificate Closure；
4. Main与Lab虽然进程或项目分离，却共享同一错误假设；
5. Linkage和Hash正确锁定同一Artifact，但不能证明Artifact行为正确；
6. Target专属Rule、数量、字段、工具和拓扑可能被误升为平台默认值。

这些抽象问题可以进入Core设计；案例中的产品名、Artifact字段、候选数量、领域语法、模型、Lane、阈值和专属拓扑只能留在Target Profile或Case Fixture。

### 3.2 Core不得读取什么

Normative Core不得读取案例叙事、案例专属输入、已知失败答案或Fixture期望结果来决定Schema、Gate、状态机、CLI和运行路由。案例只允许：

- 产生Candidate Finding；
- 填写已冻结的Target Profile Extension Point；
- 作为Positive、Negative、Tamper或Ablation Fixture；
- 为Case-to-Core Promotion提供一份来源证据。

来源案例的完整Requirement、Finding、只读重算、专属Canary、验收条件和候选生产拓扑保存在独立非规范文件中。该文件不是Core编译输入，也不证明v2.9已经实现或认证。

## 4. 通用根因分析

### 4.1 因果链

```text
行为/语义Requirement没有原子化Executor、Topology和Evidence义务
  ↓
Requirement被错误分配结构或自报式verification_mode
  ↓
Coverage只到Producer，没有到Independent Oracle和Certificate Claim
  ↓
Producer选择成本更低但语义不足的替代实现
  ↓
Producer自报PASS，Validator重复检查相同弱不变量
  ↓
Linkage、Hash、安装和证书正确锁定同一个弱验证Artifact
  ↓
形式闭环为绿，真实行为仍不满足Requirement
```

### 4.2 根因平面

| 层级 | 通用根因 | 正确修复位置 |
|---|---|---|
| Intent | 关键语义、负向边界或Executor要求没有冻结 | Expert Intent Lock与Requirement IR |
| Architecture | Capability没有生产路径，或Stage/Subharness/Module职责错误 | Architecture Decision IR与Topology Lock |
| Rule/Capability | Domain Rule、Governance Policy、Heuristic、Target Capability和Oracle混写 | 分层Catalog与Profile Binding |
| Controller | 模型自由决定循环、重试、工具、停止与降级 | Deterministic Run Contract |
| Producer | 使用模板、占位实现、自报指标或替代Executor | Producer/Module直接行为修复 |
| Oracle | Validator与Producer共享假设或只查结构 | Independent Oracle与Adversarial Fixture |
| Certification | 高等级Claim被低等级Evidence关闭 | Evidence Compatibility与Claim Closure |

### 4.3 Five Whys结论

1. 为什么形式流程可以PASS而行为仍错误？因为验证链证明了Artifact身份与结构，却没有证明目标行为；
2. 为什么没有证明目标行为？因为Requirement没有被编译成匹配的Runtime Evidence和Independent Oracle；
3. 为什么编译阶段没有拒绝？因为Requirement Type、Architecture、Executor与Evidence兼容性不是Freeze硬门；
4. 为什么独立Lab也可能PASS？因为组织或进程分离没有消除共享实现、共享上下文和共享假设；
5. 为什么问题会扩散为平台复杂度？因为案例Finding可能直接推动新增Gate、分支和Subharness，而没有先分类、抽象和执行Control Flow Delta。

最终系统根因不是单个Validator太弱，而是生产设计、规则执行、证据义务和案例晋升边界没有形成一条可执行闭环。

## 5. v2.9 升级目标

### 5.1 必须实现

1. 为每个 Requirement Atom 声明正交的 Requirement Kinds、Verification Obligations、Lifecycle Scopes 和 Criticality；
2. 为行为和语义 Requirement 强制生成 Evidence Obligation；
3. 为语义 Requirement 强制定义独立 Oracle；
4. 明确真实 Executor 与 Fake Executor 的适用边界；
5. 禁止使用实现自报指标独立关闭 Requirement；
6. 将正向、负向和篡改用例绑定到 Requirement；
7. 记录 Target Profile 声明的 Input → Processing/Invocation → Intermediate Artifact（如有）→ Output Lineage，不假设项目必有推理、候选或选择阶段；
8. 当 Atom 声明 Runtime 行为时，将对应 Runtime Topology 纳入可验证合同；
9. 对声明独立重算义务的 Atom，要求 External Lab 从原始领域 Artifact 重算关键指标；
10. 在 Start Package 冻结前拒绝缺少其声明义务所需 Oracle/Evidence 的 Requirement；
11. 保持 v2.8 已有的 Hash、SQLite、授权、Artifact 和安装链能力；
12. 保持 Factory 只编译候选，不执行生成的 Workpack；
13. 为每个下游执行里程碑生成一个 Canonical Authorization Bundle，并以单一 Root Hash 绑定其全部 Input、Plan、Contract、Executable、Validator、权限、预算、停止门和状态基线；
14. 将“人工是否授权”与“机器逐项校验 Hash”分离，用户只确认可读风险摘要和一个 Bundle Root/短挑战口令；
15. 在请求人工授权前完成无副作用 Authorization Readiness Preflight，提前拒绝路径缺失、Schema 不兼容、自 Hash、序列化、权限配置、CLI 参数和静态边界错误；
16. 在同一 Bundle 范围内支持 `advance-until-gate` 和限定自动重试，避免逐节点人工确认；
17. 当 Driver、Executor、Validator、Schema、权限、外发范围、真实目标或停止门发生变化时强制生成新 Bundle 并返回人工门；
18. 保留所有子 Hash、Receipt 和独立验证证据，Root Hash 只减少人工输入，不降低机器校验强度。
19. 将冻结宪章编译为可机器判定的 Policy IR、策略测试和运行时 Decision Receipt，使关键条款在工具调用、状态迁移和停止点被确定性执行；
20. 为有经验的操作者提供基于不确定性、问题价值和反例的 Expert Elicitation，强化多轮意图锁定而不是增加面向新手的教程式对话；
21. 以事件日志、幂等键、租约、心跳、Checkpoint 和 Resume Capsule 支持可恢复长任务，预算耗尽默认形成可验证检查点而非丢失上下文的笼统 STOP；
22. 建立按风险分流的 Review Router 和 Budget Governor，将人工判断集中在权限、不可逆影响、外发、waiver、未知副作用和高不确定性处；
23. 使 Factory、生成的 Harness 和验证组件能够从干净 Git clone 在不同设备与用户名下复现，不依赖本机绝对路径、同级目录、未声明插件、隐式凭据或聊天记忆；
24. 将环境、工具、插件/MCP、模型能力、权限、Secret 和离线降级方式写入机器可读 Manifest 与 README；
25. 显式评估 Main、Lab、Linkage 之间的共同失效风险；三个 CLI 名称、三个子进程或同一聊天里的三个 Agent 不得自动被认定为独立证据源。
26. 在 Requirement Freeze 后、Workpack 路由前生成 `ARCHITECTURE_DECISION_IR`，先定义能力、行为、状态、数据流、决策点和失败路径，再决定 Harness 由哪些 Stage、Subharness 和 Module 构成；
27. 将领域 Rule、治理 Policy、启发式 Heuristic、Target Capability Constraint 和 Validator Oracle 分开建模，禁止把它们全部隐藏在 Prompt 或知识库里；
28. 由确定性 Controller 持有循环、分支、阶段转换、预算、重试和停止权；LLM 只在显式 `SEMANTIC_DECISION_SLOT` 内推理或生成；
29. 为每个 Stage/Subharness/Module 生成 Typed Input/Output、State Ownership、Allowed Tools、Applicable Rules/Policies、Retry/Return Path 和 Context Budget；
30. 建立 Production-first Repair Order：Intent/Architecture/Rule/Planner/Executor 优先，Policy Enforcement 其次，Validator/Certificate 最后；产出仍错误时不得用增加校验替代生产修复；
31. 在同一 Codex Chat 内只允许声明 `COORDINATED_SEPARATION`，不声明认证级独立；真正独立证据必须来自不共享聊天上下文和发布权的顶层运行/外部控制域。
32. 将 Normative Core、Target Profile 与 Case/Fixture 物理分层并建立单向依赖；Core 不得读取案例内容、案例名称或案例专属路由；
33. 建立 `CASE_TO_CORE_PROMOTION` 规则：单一案例只能产生 Candidate Finding，只有领域无关不变量能够形式化证明，或同一问题在至少两个非来源、彼此不同的 Target Profile 中独立复现时，才可提议升级为平台规则；安全边界例外仍需显式架构批准；
34. Target Profile 只能实例化已冻结 Extension Point，不得在加载时新增平台 State、Gate、CLI、Stage 类型、重试语义或停止语义；确需改变 Core 时必须启动独立 Architecture Reopen；
35. 对每次升级生成 `CONTROL_FLOW_DELTA`，逐项报告新增、替换和删除的状态、分支、Stage、Subharness、人工门、重试、回退与外部依赖；没有必要性、替代方案和总复杂度影响说明的净新增不得进入 Architecture Lock；
36. Canary 按“要证明的性质”最小化，不按完整业务故事复制；发布前执行案例消融测试，证明移除来源案例后 Core 行为、Schema 和路由保持不变。

### 5.2 非目标

v2.9 不负责：

- 由 Factory 直接评价目标领域产出是否“好”；领域判断必须由 Target Profile 声明的 Oracle 执行；
- 由 Factory 调用目标产品 Runtime、外部模型或业务服务；
- 由 Factory 执行作为需求输入或目标资源提供的可执行 Payload；具体资源和执行形态只属于Target Profile；
- 由 Factory 自动批准执行授权；
- 以一个 Root Hash 隐藏或扩大真实权限范围；
- 在 Executor、Validator、权限或外发契约变化后静默复用旧授权；
- 让 Linkage 代替 External Lab；
- 让 Hash 代替行为验证；
- 自动修改历史 Start Package；
- 破坏 v2.8 Program 的独立 SQLite 状态。
- 把同一父任务中的多个子 Agent、同一凭据下的多个 CLI 或同一实现的重复运行包装成“独立认证”；
- 把 Dev Container、MCP/A2A 协议或上传 GitHub 本身误当作可移植性、权限隔离或供应链可信性的充分证明；
- 让自然语言策略自动生成器未经策略测试和批准就成为授权源。
- 让 LLM 自由决定整个 Harness 的循环、阶段、停止和回退，再依靠事后 Validator 兜底；
- 把 Stage、Subharness、Module、Rule、Policy、Heuristic、Oracle 当作同义词；
- 把同一 Chat 内由父 Agent 启动的盲化子任务提升为 `INDEPENDENT_CERTIFICATION`；它最多减少上下文污染和部分共同失效。
- 从单个案例直接增加平台 Gate、状态、Stage、Subharness、CLI、重试或停止链路；
- 让 Target Profile、Fixture、示例或 Canary 在加载时修改 Normative Core 的控制流；
- 为了覆盖每个已知案例而持续追加平行策略链；案例变化应优先转化为 Profile 数据、Rule Candidate 或现有 Extension Point 的参数。

## 6. 目标架构

```text
Source / User Input
  ↓
Expert Elicitation and Intent Hypothesis Set
  ↓
Requirement Atom
  ├── Requirement Kinds
  ├── Verification Obligations
  ├── Lifecycle Scopes
  ├── Criticality
  ├── Forbidden Proxies
  └── Evidence Obligations
  ↓
Capability and Behavior Decomposition
  ├── capability graph
  ├── behavior/state model
  ├── decision points
  ├── data/context flow
  └── failure/return paths
  ↓
Architecture Decision IR
  ├── Stages
  ├── Subharnesses
  ├── Deterministic Modules
  ├── Semantic Decision Slots
  └── State/Context Ownership
  ↓
Rule and Policy Compilation
  ├── Domain Rules
  ├── Governance Policies
  ├── Heuristics
  ├── Target Capability Constraints
  └── Oracle Rules
  ↓
Deterministic Run Contract
  ↓
Coverage Graph v2
  ├── Build Workpack
  ├── Runtime Proof Contract
  ├── Deterministic Oracle
  ├── Independent Semantic Oracle
  ├── Positive Fixture
  ├── Negative Fixture
  ├── Tamper Fixture
  └── Certification Check
  ↓
Start Package Candidate
  ↓ Human Approval
Executable Charter Policy Bundle
  ↓ Policy Decision / Enforcement Point
Build Program / Driver
  ↓ Authorization Readiness Preflight
Authorization Bundle Ready
  ↓ Human Risk Decision on Bundle Root
Authorized advance-until-gate
  ↓
Main Implementation Evidence
  ↓
External Lab Independent Recalculation
  ↓
Linkage Identity and Interface Binding
  ↓
Certification
  ↓
Certified Release Lock
  ↓
Portable Source/Artifact Release + Provenance
```

所有状态变化由 Durable Runtime 的权威事件流和 CAS 驱动；Controller 根据冻结的 Architecture/Rule/Policy/Run Contract 决定允许的下一步。LLM 负责填充显式语义决策槽、提出候选和解释，不保存唯一状态，不改变拓扑，不创建新工具权限，也不得绕过 Policy Enforcement Point。Main、Lab 和 Linkage 通过不可变 Artifact Envelope 交接，协调者可以调度它们，但不得替任一独立控制域出具结果或签名。

## 7. Requirement 类型系统

### 7.1 禁止用单一枚举混合不同维度

原提案把 `NORMATIVE`、`STRUCTURAL`、`BEHAVIORAL`、`SEMANTIC`、`ADVERSARIAL`、`INSTALLATION` 放入一个 `verification_class`。这混合了：

- Requirement 内容性质；
- 验证方法；
- 生命周期阶段；
- 对抗测试义务。

同一个 Atom 可能同时要求文本无损、Runtime 行为、输出语义、负向拒绝和安装回读，强制“六选一”会再次发生降级。v2.9 应改为正交字段：

| 字段 | 示例值 | 规则 |
|---|---|---|
| `requirement_kinds[]` | `STRUCTURAL_SHAPE`、`RUNTIME_BEHAVIOR`、`OUTPUT_SEMANTICS` | 描述要求本身，可多选 |
| `verification_obligations[]` | `SCHEMA_VALIDATION`、`RUNTIME_PROCESS_PROOF`、`DETERMINISTIC_RECOMPUTATION`、`INDEPENDENT_SEMANTIC_REVIEW`、`NEGATIVE_TEST`、`TAMPER_TEST` | 描述必须完成的证明，可多选 |
| `lifecycle_scopes[]` | `AUTHORING`、`BUILD`、`RUNTIME`、`EXTERNAL_LAB`、`CERTIFICATION`、`INSTALLATION` | 描述关闭点，可多选 |
| `criticality` | `BLOCKING`、`HIGH`、`NORMAL` | 描述缺证据时的停止级别 |
| `classification_status` | `CLASSIFIED`、`UNCLASSIFIED` | `UNCLASSIFIED` 仅用于迁移暂存，禁止 Freeze |

`ADVERSARIAL` 不再是 Requirement 类型，而是 `NEGATIVE_TEST` / `TAMPER_TEST` 验证义务；`INSTALLATION` 不再与语义类型互斥，而是生命周期范围和对应证明义务。

### 7.2 Requirement Atom v2.9通用Profile示例

以下示例只演示通用字段形状，不绑定产品、Provider、Artifact名称、数量、Topology或阈值：

```json
{
  "atom_id": "ATOM-BEHAVIOR-001",
  "source_refs": ["REQ-001"],
  "requirement_kinds": ["RUNTIME_BEHAVIOR", "OUTPUT_SEMANTICS"],
  "verification_obligations": [
    "REAL_EXECUTION",
    "INDEPENDENT_RECOMPUTATION",
    "NEGATIVE_TEST"
  ],
  "lifecycle_scopes": ["RUNTIME", "CERTIFICATION"],
  "criticality": "HIGH",
  "executor_profile_ref": "profile://target/executor",
  "evidence_obligation_refs": ["EO-ATOM-BEHAVIOR-001"],
  "oracle_contract_refs": ["ORACLE-ATOM-BEHAVIOR-001"],
  "architecture_decision_refs": ["ADR-ATOM-BEHAVIOR-001"],
  "positive_case_refs": ["CASE-POS-001"],
  "negative_case_refs": ["CASE-NEG-001"],
  "failure_return_path": "ARCHITECTURE_OR_PRODUCER_REPAIR",
  "classification_status": "CLASSIFIED"
}
```

Profile可以给这些引用绑定领域数据，但不能创建新字段语义、平台状态或控制流。平台Schema不得为任何Target提供隐藏默认值。

### 7.3 Atom 拆分与关闭规则

如果同一句 Requirement 中的子要求可以由不同证据独立关闭，编译器必须拆 Atom。例如：

```text
“输出集合满足Profile声明的基数约束，并在声明的语义维度上互异”
  → ATOM-CARDINALITY: profile-defined cardinality
  → ATOM-SEMANTIC-DIVERSITY: profile-defined semantic distinction
```

只有当子要求不可分割时才保留单一 Atom，并对全部 `verification_obligations` 执行 `ALL_OF`。不得选取最容易的结构证据关闭整个混合 Atom。

必须增加以下硬规则：

```text
OUTPUT_SEMANTICS Requirement
  cannot_be_closed_by:
    STRUCTURAL evidence only
    LINKAGE evidence only
    INSTALLATION evidence only
    producer self-report only

UNCLASSIFIED Requirement
  cannot_cross:
    READY_FOR_READBACK
    REQUIREMENTS_FREEZE
```

## 8. Evidence Obligation

### 8.1 新增对象

每项行为或语义Requirement必须绑定至少一个`evidence_obligation`。通用形状如下：

```json
{
  "evidence_obligation_id": "EO-ATOM-BEHAVIOR-001",
  "atom_id": "ATOM-BEHAVIOR-001",
  "required_executor_role": "TARGET_RUNTIME",
  "real_execution_required": true,
  "required_evidence_types": [
    "INVOCATION_RECEIPT",
    "RAW_OUTPUT_ARTIFACT",
    "INDEPENDENT_ORACLE_RESULT"
  ],
  "forbidden_substitutions": [
    "IMPLEMENTATION_SELF_REPORT",
    "SCHEMA_ONLY",
    "HASH_ONLY",
    "LINKAGE_ONLY",
    "INSTALLATION_ONLY"
  ],
  "runtime_topology_contract_ref": "TOPOLOGY-ATOM-BEHAVIOR-001",
  "oracle_contract_ref": "ORACLE-ATOM-BEHAVIOR-001",
  "positive_case_refs": ["CASE-POS-001"],
  "negative_case_refs": ["CASE-NEG-001"],
  "tamper_case_refs": ["CASE-TAMPER-001"],
  "certificate_claim_refs": ["CLAIM-ATOM-BEHAVIOR-001"],
  "failure_return_path": "PRODUCTION_ROOT_CAUSE_ROUTER"
}
```

Target Profile负责提供具体Executor、Artifact、Fixture和Oracle绑定；Core只验证类型兼容性、来源、完整性和关闭路径。

### 8.2 Evidence 类型约束

证据必须声明：

- Producer；
- Validator；
- 原始对象；
- 计算方法；
- Hash；
- 是否允许共享代码；
- 是否需要独立进程；
- 是否需要真实 Executor；
- 是否允许 Fake；
- 失效条件；
- Return Path。

这些字段不是凭空新增概念，而是把 v2.8 已定义的 challenge、process lineage、raw trace、environment、attestation 和独立证据源编译为 Atom 级必填合同。Evidence Validator 还必须检查：

1. 所有实际出现的 Scope 字段与授权一致；`run_id/stage_id/attempt_id` 属于通用 Core，`lane_id` 仅在 Target Profile 声明 Lane 时校验；
2. `started_at < ended_at`，并落在授权有效窗口内；
3. PID/parent PID 与受控 Runner 的进程谱系一致；
4. Input、Output、Raw Events、Environment 均有 Hash；
5. Attestation 由 Lab/Trusted Runner 所有的 Key 签名；
6. 原始 Trace 中的敏感值已按 Redaction Manifest 脱敏，Hash 与脱敏前受控摘要关系可回读；
7. Producer JSON 中同名字段不能替代 Trusted Runner Receipt。

## 9. Independent Oracle Contract

### 9.1 Oracle必填字段

平台只规定Oracle Contract的形状、独立性和关闭规则，不规定领域字段、算法或阈值：

```json
{
  "oracle_id": "ORACLE-ATOM-BEHAVIOR-001",
  "atom_id": "ATOM-BEHAVIOR-001",
  "profile_scope": "profile://target",
  "oracle_kind": "DETERMINISTIC_OR_SEMANTIC_RECOMPUTATION",
  "implementation_ref": "resource://oracle/implementation",
  "implementation_sha256": "<REAL_SHA256>",
  "algorithm_version": "profile-defined",
  "input_artifact_types": ["RAW_TARGET_OUTPUT"],
  "metric_contract": "profile-defined",
  "threshold_policy": "profile-defined",
  "unknown_policy": "FAIL_CLOSED",
  "independence": {
    "separate_process": true,
    "separate_state": true,
    "producer_summary_trusted": false,
    "shared_final_judgment_function": false
  },
  "expected_finding_ids": ["PROFILE_DEFINED_FINDING"],
  "result_schema_ref": "schema://oracle-result/v1"
}
```

`<REAL_SHA256>`是Schema说明中的待物化值；Candidate不得保留占位符。Oracle必须在Freeze前绑定真实实现、Hash、版本、输入类型、Unknown策略、预期Finding和结果Schema。

### 9.2 验证器独立性

最低要求：

1. Main 与 Lab 不共享最终判定函数；
2. Lab 在独立进程中运行；
3. Lab 从Target Profile声明的原始领域输出重新计算Requirement-specific指标，不采信Producer汇总值；具体字段和指标只在Profile中定义；
4. 当 Atom 声明 Runtime Topology 时，Lab 从受控 Runner Receipt 重新统计拓扑；未声明 Topology 的项目不得被强制要求 Lane 或调用次数；
5. Lab 不采信实现输出的 `status=PASS`；
6. 仅当 Atom 声明 `real_execution_required=true` 时，认证才必须执行真实 Executor 正向矩阵；纯结构型项目不得被强制引入 Runtime；
7. Fake Launcher 仅用于单元测试和故障注入。
8. Lab 不得只修改 Producer 的内部表示后复用 Producer Validator 作为语义篡改测试；internal representation 只是 source-case Profile 中的内部表示实例；
9. 每个 Certificate 语义 Claim 必须反向绑定 Oracle Result Hash、原始 Artifact Hash 和 Fixture Set Hash；
10. 阈值变更必须产生新的 Oracle Version，不得对旧证书静默重算。

## 10. Runtime Topology Contract

Runtime Topology是Target Harness的Requirement Profile，不是Foundry平台的固定执行图。Foundry只验证“冻结声明与真实Receipt是否一致”。

通用Topology Contract至少包含：

```json
{
  "topology_id": "TOPOLOGY-ATOM-BEHAVIOR-001",
  "atom_id": "ATOM-BEHAVIOR-001",
  "executor_profile_ref": "profile://target/executor",
  "invocation_policy": {
    "min": 1,
    "max": 1,
    "parallelism": "PROFILE_DEFINED"
  },
  "input_binding": "artifact://normalized-input",
  "output_binding": "artifact://raw-target-output",
  "required_receipt_fields": [
    "executor_identity",
    "executable_hash",
    "input_hash",
    "output_hash",
    "started_at",
    "completed_at",
    "exit_status"
  ],
  "retry_policy_ref": "run-contract://retry",
  "budget_policy_ref": "run-contract://budget",
  "failure_return_path": "RUNTIME_OR_ARCHITECTURE_REPAIR"
}
```

具体项目可以声明零次远端调用、一次确定性CLI调用、多进程服务调用或受控语义Executor；数量、并行度、Provider和Artifact均来自Profile。未声明Topology的项目不得被平台强制生成额外Lane、Agent、Runtime或Oracle。

## 11. Coverage Graph v2

### 11.1 从路由覆盖升级为履约覆盖

旧图：

```text
Atom → Workpack → Stage → Release Step → Owner
```

新图：

```text
Atom
├── Build Workpack
├── Runtime Evidence Obligation
├── Deterministic Oracle
├── Independent Oracle
├── Positive Fixture
├── Negative Fixture
├── Tamper Fixture
├── Linkage Binding
└── Certification Check
```

上图是节点全集，不是每个 Program 的固定形状。Compiler 必须根据 `verification_obligations[]` 选择适用节点；不适用节点写入 Applicability Index 为 `NOT_APPLICABLE`，不得生成空壳 Oracle、Fake Runtime 或无来源 Fixture。

### 11.2 冻结前完整性规则

冻结前门禁必须按 Atom 的正交分类条件化，而不是给所有项目套用同一验证拓扑：

- `RUNTIME_BEHAVIOR` 缺少与 `required_executor` 一致的 Runtime Evidence；
- `OUTPUT_SEMANTICS` 缺少独立 Oracle 或原始领域输出绑定；
- 声明 `NEGATIVE_TEST` / `TAMPER_TEST` 义务却缺少对应 Fixture；
- `STRUCTURAL_SHAPE` 被无依据地强制要求真实 Runtime 或语义 Oracle；
- Target Profile 的 Executor、Topology、Oracle 或阈值未由冻结 Atom 推导；
- 没有明确 PASS Logic；
- 没有 Failure Return Path；
- 声明真实 Executor 却未绑定 Fake 与 Real 的认证边界。

## 12. Factory 新门禁

### 12.1 `REQUIREMENT_TYPE_COMPLETENESS`

每个 Atom 必须满足：

- `classification_status=CLASSIFIED`；
- `requirement_kinds[]` 非空；
- `verification_obligations[]` 非空；
- `lifecycle_scopes[]` 非空；
- 混合结构/语义要求已拆 Atom，或显式使用 `ALL_OF`。

### 12.2 `ORACLE_COVERAGE_COMPLETE`

`RUNTIME_BEHAVIOR` Atom 必须具备可执行行为验证；`OUTPUT_SEMANTICS` Atom 必须具备独立领域 Oracle。纯结构 Atom 不得因本门禁被迫引入语义 Oracle。

### 12.3 `EVIDENCE_TYPE_COMPATIBLE`

禁止用低等级证据关闭高等级 Requirement。

示例：

```text
OUTPUT_SEMANTICS Requirement + STRUCTURAL Evidence only = FAIL
```

### 12.4 `EXECUTOR_ROLE_UNAMBIGUOUS`

必须区分：

- Target Runtime；
- Build Program Driver；
- Coding Agent Executor；
- Product Semantic Executor；
- Verification Executor；
- Certification Installer。

### 12.5 `VALIDATOR_INDEPENDENCE_DECLARED`

必须声明 Producer、Validator、共享代码限制和重算策略。

### 12.6 `NEGATIVE_AND_TAMPER_COVERAGE_COMPLETE`

每个关键 Requirement 必须有负向或篡改场景。

### 12.7 `RUNTIME_PROOF_REQUIRED`

如果 Requirement 声明真实 Executor，缺少真实运行证据不得认证。

### 12.8 `PLATFORM_GENERICITY_NO_DOMAIN_HARDCODE`

平台核心 Schema、Factory Gate、状态机、CLI、迁移器和 Release Gate 中不得出现只属于某个 Target Profile 的：

- 产品名、Provider 名或模型名；
- 领域 Artifact 名和字段路径；
- 固定候选数量、Lane 数、调用次数或阈值；
- Target-specific Oracle、Fixture 或 Finding 默认值。

允许这些值出现在带`profile_scope`的Target Profile、案例说明、测试Fixture和Canary证据中。审计必须证明平台从冻结Atom/Profile读取参数，而非对任何案例名、领域字段、Provider、内部表示或固定Topology进行分支判断。

### 12.9 `AUTHORIZATION_BUNDLE_CLOSURE_COMPLETE`

Start Package 只能规划 Bundle Contract，Factory 不授予执行权限。编译期必须证明每个下游授权包能够形成闭合清单，至少覆盖：

- Program、Milestone、State Hash/Revision 与幂等身份；
- Input Lock、Plan、Contract、Driver、Executor、Validator 与 Schema；
- 允许的读写根、外发分类、网络、环境、预算、最大 attempt 和停止门；
- 依赖 Artifact、Result、Receipt、历史只读边界和禁止动作；
- 子项相对路径、字节数、SHA-256、用途和 Canonicalization Version。

缺失任一强制子项时不得生成可授权 Bundle Root。

### 12.10 `AUTHORIZATION_READINESS_PREFLIGHT_COMPLETE`

所有无需执行目标 Workpack 即可发现的问题必须在展示人工授权挑战前关闭，包括：

- 逻辑 URI/仓库相对路径的合法性，以及 Runtime Binding 解析后本次执行所需实际路径的存在性、可读性和可执行性；运行时绝对路径不得写回发行物；
- Schema subset/full-schema 绑定；
- Driver、Wrapper、Common、Executor、Validator 自 Hash；
- 授权 JSON 可序列化和可回读；
- 权限配置、CLI argv、Prompt/ARG_MAX、超时与 `stdin=DEVNULL` 契约；
- promotion identity、attempt budget、结果命名空间和 fail-closed blocker 一致性。

Readiness Preflight 不能执行 Workpack、创建正式 Session、消费授权或修改目标 workspace。

### 12.11 `HUMAN_GATE_RISK_DELTA_JUSTIFIED`

每个人工门必须声明相对上一门的风险增量。若仅是同一已授权命令的暂时性重试、相同 Hash 的只读复验或 attempt-scoped 证据收口，应由 Bundle 内自动推进处理；若涉及执行机制、权限、外发、真实目标、waiver 或不可逆影响变化，则必须返回人工门。

### 12.12 `CHARTER_POLICY_EXECUTABLE_AND_TRACEABLE`

每条会改变权限、状态、外发、停止条件或认证结论的宪章条款，必须具有稳定 Clause ID，并绑定：

- 可机器判定的 `CHARTER_POLICY_IR`；
- 正向、负向和冲突策略测试；
- Policy Decision Point 与实际 Tool/State Enforcement Point；
- 输入世界状态、决策、理由、策略版本和结果的 Decision Receipt；
- 不可自动形式化条款的显式人工决策点。

自然语言宪章仍是人类可读来源，但不能只靠 Agent 在长上下文中“记住并自觉执行”。同一模型生成的 Policy IR 不得未经独立测试和人工 Freeze 直接成为权威策略。

### 12.13 `PORTABLE_PACKAGE_NO_LOCAL_BINDING`

计划上传 GitHub 或供他人使用的 Platform Core、Target Package、生成 Harness 和 README 必须：

- 不含本机绝对路径、`file://`、越出仓库的 `../`、外部符号链接或隐式同级仓库引用；
- 使用仓库相对路径或 `repo://`、`artifact://sha256/...`、`tool://`、`profile://`、`secret://` 等逻辑 URI；
- 将逻辑资源到本机路径的映射保存在不进入发行物的 Runtime Binding 中；
- 显式声明 OS/架构、运行时、工具、插件/MCP、模型能力、权限、Secret、网络和离线行为；
- 通过干净 clone、随机路径、不同用户名和声明平台矩阵的复现测试。

### 12.14 `EXPERT_INTENT_UNCERTAINTY_CLOSED`

Freeze 前必须区分“需求尚不明确”与“模型自己不确定”，维护可检查的 Intent Hypothesis Set 与 Decision Ledger。系统按问题的预期信息价值、风险影响和回答成本选择下一批问题；高关键歧义、冲突和无来源假设不得被聊天摘要静默吞掉。每个关键 Atom 至少绑定示例/反例、证据 Oracle、Owner 和 Failure Return Path。

### 12.15 `CONTROL_DOMAIN_COMMON_MODE_RISK_ASSESSED`

Main、External Lab、Linkage、Policy、Orchestration 和 Release 之间必须声明独立性向量，至少包括：项目/角色、进程、任务上下文、workspace、状态库、凭据/签名、模型/Provider、Validator 实现、网络与 Secret Scope。若同一父任务、同一实现、同一凭据或同一可写状态形成共同失效路径，必须降级独立性声明或增加确定性 Oracle、异构实现、独立签名/权限与盲测。

### 12.16 `DURABLE_CHECKPOINT_AND_BUDGET_RESUME_READY`

长任务必须在每个已提交节点后生成可重放事件和 Resume Capsule。预算、进程或暂时依赖中断时，若不存在未知副作用，应进入 `BUDGET_CHECKPOINT_READY` 或 `TRANSIENTLY_INTERRUPTED_RESUMABLE`，保存精确 State Hash、已完成证据、未完成节点、授权有效期和剩余预算；恢复前必须重新检查授权时效、环境与 Artifact 漂移。只有状态不唯一、未知副作用或策略冲突才进入硬人工阻断。

### 12.17 `PRODUCTION_ARCHITECTURE_COMPLETENESS`

Requirement Freeze 后必须生成可解释的 Architecture Decision IR，至少覆盖 Capability、Behavior/State、Data/Context Flow、Decision Point、Failure/Return Path、Module Boundary 和非目标。缺少生产架构时不得直接从 Atom 跳到 Workpack 或 Validator。

### 12.18 `STAGE_SUBHARNESS_MODULE_CLASSIFICATION_COMPLETE`

每个执行单元必须被明确分类：

- `STAGE`：同一控制器下的有序生命周期阶段；
- `SUBHARNESS`：具有自身目标、状态、上下文、工具集和局部循环的受控子系统；
- `MODULE`：无自主控制流的可复用确定性函数/服务；
- `SEMANTIC_DECISION_SLOT`：只在指定输入输出边界内调用 LLM 的推理槽。

分类必须说明为什么不是其他类型。禁止为并行或“看起来更智能”而创建空壳 Subharness，也禁止把需要局部状态/重试的复杂闭环伪装成单一 Module。

### 12.19 `RULE_POLICY_HEURISTIC_ORACLE_SEPARATION`

每条隐性或显性约束必须归入且只能以明确关系跨入以下类别：

- `DOMAIN_RULE`：业务上必须怎样转换或选择；
- `GOVERNANCE_POLICY`：谁在什么条件下可以做什么；
- `HEURISTIC`：效果可能更好但允许被证据推翻的经验策略；
- `TARGET_CAPABILITY_CONSTRAINT`：目标工具/模型/环境能做什么；
- `ORACLE_RULE`：如何独立判断结果。

必须记录来源、优先级、Hard/Soft、冲突顺序、适用 Stage/Subharness、允许修改者和决策回执。Prompt 中存在但目录中未声明的关键隐性规则必须形成 Finding。

### 12.20 `DETERMINISTIC_CONTROL_FLOW_OWNERSHIP`

循环、分支、阶段转换、工具允许列表、预算、最大重试、停止和回退必须由冻结 Run Contract 与确定性 Controller 持有。LLM 不得自行创建 Stage、扩展工具、绕过返回路径或把失败改写为成功；它只能在 `SEMANTIC_DECISION_SLOT` 内返回满足 Schema 的候选。

### 12.21 `PRODUCTION_FIRST_REPAIR_ORDER_ENFORCED`

每个 Finding 必须声明根因平面：`INTENT`、`ARCHITECTURE`、`DOMAIN_RULE`、`POLICY`、`PLANNER_CONTROLLER`、`EXECUTOR`、`VALIDATOR_ORACLE`、`ENVIRONMENT` 或 `CERTIFICATION`。当原始产出错误且根因位于前六类时，Repair Plan 必须先修改生产路径并运行直接行为回归；只增加 Validator、Fixture 或证书条件不能关闭根因 Finding。

### 12.22 `SAME_CHAT_INDEPENDENCE_CLAIM_BOUNDED`

同一父 Codex Chat 发起的 Subagent/CLI，即使采用不同 Prompt、worktree 或模型，也只能声明 `COORDINATED_SEPARATION`。它们必须使用盲化输入、不可变 Artifact Envelope、独立workspace/state/output、最小权限和确定性聚合器；父 Chat 不得改写结果。若 Claim 需要 `INDEPENDENT_CERTIFICATION`，必须由不继承该 Chat 上下文、拥有独立身份/Signer/发布权的顶层运行或外部控制域完成。

### 12.23 `ARCHITECTURE_TO_RUN_TRACEABILITY_COMPLETE`

每个 Capability 和关键 Rule 必须正向追踪到 Stage/Subharness/Module、Typed Interface、State Owner、Tool Binding 和 Run Transition，并反向追踪到 Requirement Atom。任何 Workpack、Subharness、Module 或工具调用没有 Requirement/Architecture来源，或任何关键能力没有生产实现路径时，均不得生成候选。

### 12.24 `CASE_INFLUENCE_BOUNDED`

每个由案例触发的平台变更必须登记其抽象问题、来源案例、非适用范围和晋升依据。单一案例及其同源变体只能形成 Target Profile/Rule Candidate/Finding，不能直接形成 Core 默认值或新控制流。平台晋升必须满足以下任一条件：

- 该规则是可形式化说明的领域无关不变量；
- 同一缺陷在至少两个非来源、彼此不同的 Target Profile 中独立复现；
- 属于必须立即封闭的安全或权限边界，并经过显式 Architecture Review，记录为何不能等待跨领域复现。

Core 构建和测试必须支持 `case_inputs=disabled`。关闭案例输入后若 Schema、Gate、状态机、CLI 或路由发生变化，判定失败。

### 12.25 `CONTROL_FLOW_DELTA_BUDGETED`

每次 Architecture Epoch 必须输出控制流差量，而不是把新策略和链路静默叠加到旧拓扑。差量至少包含：新增/替换/删除的状态、分支、Stage、Subharness、人工门、重试、回退、Oracle 和外部依赖，以及对延迟、成本、恢复、可移植性和共同失效面的影响。

默认决策顺序是：参数化现有节点 → 替换错误节点 → 复用现有 Extension Point → 最后才净新增控制节点。案例只要求不同内容、阈值、规则或工具绑定时，必须留在 Target Profile；不能以“支持该案例”为理由增加平台转向策略。无法说明为何现有节点不能承载、为何替换不足以及新增后如何删除旧路径时，不得 Architecture Lock。

## 13. 状态机升级

建议新增状态：

```text
CLARIFYING_REQUIREMENTS
→ BUILDING_INTENT_HYPOTHESES
→ WAITING_HIGH_VALUE_CLARIFICATION
→ WAITING_INTENT_CONFLICT_RESOLUTION
→ WAITING_REQUIREMENT_TYPE_COMPLETION
→ WAITING_CHARTER_POLICY_COMPLETION
→ WAITING_CAPABILITY_DECOMPOSITION
→ WAITING_ARCHITECTURE_DECISION_COMPLETION
→ WAITING_TOPOLOGY_CLASSIFICATION
→ WAITING_RULE_POLICY_SEPARATION
→ WAITING_RUN_CONTRACT_COMPLETION
→ WAITING_ORACLE_COVERAGE_COMPLETION
→ WAITING_EVIDENCE_CONTRACT_COMPLETION
→ READY_FOR_READBACK
→ WAITING_REQUIREMENTS_FREEZE
→ START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
```

在下游 Runtime 增加：

```text
WAITING_AUTHORIZATION_BUNDLE_PREPARATION
AUTHORIZATION_READINESS_PREFLIGHT_FAILED
AUTHORIZATION_BUNDLE_READY
WAITING_HUMAN_RISK_DECISION
AUTHORIZED_ADVANCE_UNTIL_GATE
CHECKPOINT_COMMITTED
TRANSIENTLY_INTERRUPTED_RESUMABLE
BUDGET_CHECKPOINT_READY
WAITING_BUDGET_OR_SCOPE_DECISION
WAITING_REQUIRED_EVIDENCE
WAITING_RUNTIME_PROOF          # only if RUNTIME_PROCESS_PROOF applies
WAITING_EXTERNAL_ORACLE        # only if independent oracle applies
WAITING_ADVERSARIAL_CLOSURE    # only if negative/tamper applies
WAITING_NEW_BUNDLE_AFTER_SCOPE_OR_HASH_DRIFT
CONFORMANCE_PASS
```

任何缺少必要证据的情况必须停在明确状态，不得折叠为通用 PASS。`CONFORMANCE_PASS` 的 Claim Set 必须列出实际关闭的 Requirement Kind；纯结构 PASS 不得被表述为 Behavioral 或 Semantic PASS。`AUTHORIZATION_BUNDLE_READY` 只代表授权材料已通过无副作用自检，不代表用户已经批准或执行已经发生。

`BUDGET_CHECKPOINT_READY` 不是失败证书，也不是新增执行权限。它只证明已经安全提交的状态可恢复；任何扩大预算、延长授权、改变工具/Provider 或重新执行非幂等动作仍需按风险增量重新决策。

## 14. Factory CLI 升级

建议增加：

```text
hffactory audit-requirement-types --program-id PROGRAM_ID
hffactory audit-oracle-coverage --program-id PROGRAM_ID
hffactory audit-evidence-compatibility --program-id PROGRAM_ID
hffactory audit-validator-independence --program-id PROGRAM_ID
hffactory audit-platform-generality --program-id PROGRAM_ID
hffactory audit-portability --program-id PROGRAM_ID
hffactory audit-intent-uncertainty --program-id PROGRAM_ID
hffactory explain-next-question --program-id PROGRAM_ID
hffactory show-decision-delta --program-id PROGRAM_ID
hffactory simulate-requirement-counterexamples --program-id PROGRAM_ID
hffactory audit-charter-policy-coverage --program-id PROGRAM_ID
hffactory audit-control-domain-independence --program-id PROGRAM_ID
hffactory decompose-capabilities --program-id PROGRAM_ID
hffactory propose-architecture --program-id PROGRAM_ID
hffactory explain-topology-choice --program-id PROGRAM_ID
hffactory audit-stage-subharness-module-classification --program-id PROGRAM_ID
hffactory audit-rule-policy-separation --program-id PROGRAM_ID
hffactory compile-run-contract --program-id PROGRAM_ID
hffactory audit-architecture-run-traceability --program-id PROGRAM_ID
hffactory audit-production-first-repair --program-id PROGRAM_ID
hffactory explain-same-chat-independence --program-id PROGRAM_ID
hffactory compile-runtime-proof-contract --program-id PROGRAM_ID
hffactory compile-external-lab-contract --program-id PROGRAM_ID
hffactory compile-authorization-bundle-contract --program-id PROGRAM_ID
hffactory audit-human-gate-risk-delta --program-id PROGRAM_ID
hffactory explain-authorization-bundle --program-id PROGRAM_ID --milestone MILESTONE_ID
hffactory validate-coverage-graph-v2 --program-id PROGRAM_ID
hffactory explain-unclosable-requirements --program-id PROGRAM_ID
```

所有审计命令必须支持：

- `--json`；
- `writes_performed=false` 的只读模式；
- 稳定 Finding ID；
- Atom 级证据；
- 明确 Return Path；
- 非零失败退出码。

为避免“每发现一个问题就再增加一个 CLI”，案例去偏置不新增平行入口，而是扩展已有命令的稳定输出：

- `audit-platform-generality` 同时输出 Case → Profile → Core 依赖方向、案例晋升依据和案例消融结果；
- `audit-architecture-run-traceability` 同时输出 `CONTROL_FLOW_DELTA`、净新增节点、被替换节点和复杂度影响；
- `propose-architecture` 必须优先展示参数化、替换和复用 Extension Point 的方案，净新增 Stage/Subharness 只能作为最后候选。

Factory CLI 只编译和审计下游授权合同，不物化 `GRANTED` 授权。下游 Execution Runtime 建议提供独立入口：

```text
runtime prepare-authorization-bundle --milestone MILESTONE_ID
runtime verify-authorization-bundle --bundle-root-sha256 SHA256
runtime materialize-user-authorization --challenge-token TOKEN
runtime advance-until-gate --authorization AUTHORIZATION.json
runtime checkpoint --program-id PROGRAM_ID
runtime resume-from-capsule --capsule RESUME_CAPSULE.json
runtime explain-budget-decision --program-id PROGRAM_ID
```

其中 `prepare` 和 `verify` 不得消费授权；`materialize-user-authorization` 必须验证用户确认来自后续独立交互，并与精确 Bundle Root 绑定。

## 15. 新增 Finding 类型

```text
REQUIREMENT_CLASSIFICATION_INCOMPLETE
TARGET_SEMANTIC_EXECUTOR_UNATOMIZED
SEMANTIC_REQUIREMENT_VERIFICATION_MODE_DOWNGRADED
SEMANTIC_ATOM_LAB_ROUTE_ABSENT
NEGATIVE_CASE_DECLARED_WITHOUT_EXECUTABLE_ORACLE
REQUIREMENT_HAS_NO_RUNTIME_ORACLE
SEMANTIC_REQUIREMENT_CLOSED_BY_STRUCTURAL_EVIDENCE
IMPLEMENTATION_SELF_REPORT_TRUSTED
REAL_EXECUTOR_EVIDENCE_ABSENT
EXECUTOR_ROLE_AMBIGUOUS
VALIDATOR_NOT_INDEPENDENT
NEGATIVE_TEST_COVERAGE_ABSENT
TAMPER_TEST_COVERAGE_ABSENT
INPUT_OUTPUT_LINEAGE_UNPROVEN
RUNTIME_TOPOLOGY_UNPROVEN
DIVERSITY_PROXY_INSUFFICIENT
FAKE_EXECUTOR_USED_FOR_CERTIFICATION
SEMANTIC_AND_LINKAGE_PASS_CONFLATED
CERTIFICATE_CLAIM_NOT_BOUND_TO_ORACLE_RESULT
HISTORICAL_ACTIVE_POINTER_AMBIGUOUS
PLATFORM_DOMAIN_LITERAL_HARDCODED
PROFILE_PARAMETER_NOT_DERIVED_FROM_FROZEN_ATOM
STRUCTURAL_ONLY_PROGRAM_FORCED_INTO_RUNTIME_ORACLE
AUTHORIZATION_BUNDLE_CLOSURE_INCOMPLETE
AUTHORIZATION_BUNDLE_CANONICALIZATION_MISMATCH
AUTHORIZATION_READINESS_PREFLIGHT_INCOMPLETE
HUMAN_CONFIRMATION_REQUIRES_RAW_CHILD_HASHES
HUMAN_GATE_WITHOUT_RISK_DELTA
AUTOMATIC_RETRY_CHANGED_EXECUTION_MECHANISM
AUTHORIZATION_BUNDLE_SCOPE_SUMMARY_MISMATCH
CHARTER_CLAUSE_NOT_ENFORCED
CHARTER_POLICY_DECISION_UNTRACEABLE
POLICY_AUTHOR_AND_ENFORCER_NOT_INDEPENDENT
INTENT_HYPOTHESIS_SET_INCOMPLETE
HIGH_CRITICALITY_AMBIGUITY_UNRESOLVED
ASSUMPTION_WITHOUT_SOURCE_OR_TEST
LOCAL_ABSOLUTE_PATH_IN_RELEASE
UNDECLARED_EXTERNAL_REPOSITORY_REFERENCE
ENVIRONMENT_OR_PLUGIN_BINDING_UNDECLARED
CLEAN_CLONE_REPRODUCTION_FAILED
COMMON_MODE_FAILURE_RISK_UNASSESSED
NOMINAL_MULTI_CLI_INDEPENDENCE
BUDGET_EXHAUSTION_WITHOUT_RESUME_CAPSULE
CHECKPOINT_STATE_OR_SIDE_EFFECT_AMBIGUOUS
PRODUCTION_ARCHITECTURE_ABSENT
CAPABILITY_WITHOUT_PRODUCTION_PATH
STAGE_SUBHARNESS_MODULE_ROLE_AMBIGUOUS
SUBHARNESS_WITHOUT_LOCAL_CONTROL_LOOP
MODULE_HOLDS_UNDECLARED_ORCHESTRATION
LLM_OWNS_UNBOUNDED_CONTROL_FLOW
SEMANTIC_DECISION_SLOT_SCHEMA_ABSENT
DOMAIN_RULE_HIDDEN_IN_PROMPT
RULE_POLICY_HEURISTIC_CONFLATED
TARGET_CAPABILITY_ASSUMED_NOT_BOUND
ARCHITECTURE_DECISION_WITHOUT_REQUIREMENT_SOURCE
WORKPACK_WITHOUT_ARCHITECTURE_SOURCE
VALIDATOR_ONLY_REPAIR_LEFT_PRODUCER_UNCHANGED
ROOT_CAUSE_PLANE_MISCLASSIFIED
SAME_CHAT_COORDINATION_CLAIMED_AS_INDEPENDENT_CERTIFICATION
PARENT_ORCHESTRATOR_CAN_MUTATE_INDEPENDENT_RESULT
SINGLE_CASE_PROMOTED_TO_PLATFORM_SEMANTICS
TARGET_PROFILE_MUTATES_CORE_CONTROL_FLOW
CASE_DERIVED_STRATEGY_WITHOUT_CROSS_PROFILE_JUSTIFICATION
CANARY_FIXTURE_USED_AS_CORE_DESIGN_INPUT
CONTROL_FLOW_DELTA_UNBUDGETED
```

每个 Finding 必须包含：

- Owner；
- Requirement Atom；
- 失败证据；
- 禁止接受的替代证据；
- Return Path；
- Invalidation 范围；
- 允许的下一节点。

## 16. Start Package v2.9 新增制品

在保留 v2.8 制品的基础上新增：

```text
requirement_ir/
  REQUIREMENT_IR_V2_9.json

architecture_contracts/
  CAPABILITY_GRAPH.json
  BEHAVIOR_STATE_MODEL.json
  ARCHITECTURE_DECISION_IR.json
  HARNESS_TOPOLOGY_LOCK.json
  STAGE_INDEX.json
  SUBHARNESS_INDEX.json
  MODULE_BINDING_INDEX.json
  SEMANTIC_DECISION_SLOTS.json
  DATA_CONTEXT_FLOW.json
  ARCHITECTURE_TO_RUN_TRACEABILITY.json
  CONTROL_FLOW_DELTA.json

production_rules/
  DOMAIN_RULE_CATALOG.json
  GOVERNANCE_POLICY_BINDINGS.json
  HEURISTIC_CATALOG.json
  TARGET_CAPABILITY_CONSTRAINTS.json
  RULE_CONFLICT_RESOLUTION.json
  RULE_PROVENANCE_LEDGER.json

run_contracts/
  DETERMINISTIC_CONTROL_FLOW.json
  STAGE_TRANSITION_TABLE.json
  SUBHARNESS_RUN_CONTRACTS.json
  MODULE_TYPED_INTERFACES.json
  TOOL_CAPABILITY_BINDINGS.json
  CONTEXT_BUDGET_CONTRACT.json
  PRODUCTION_REPAIR_ORDER.json

evidence_contracts/
  EVIDENCE_OBLIGATIONS.json
  EVIDENCE_TYPE_COMPATIBILITY.json

oracle_contracts/
  ORACLE_INDEX.json
  DETERMINISTIC_ORACLES.json
  INDEPENDENT_SEMANTIC_ORACLES.json

runtime_contracts/
  EXECUTOR_ROLE_BINDINGS.json
  RUNTIME_TOPOLOGY_CONTRACTS.json
  INPUT_OUTPUT_LINEAGE_CONTRACT.json

lab_contracts/
  POSITIVE_FIXTURES.json
  NEGATIVE_FIXTURES.json
  TAMPER_FIXTURES.json
  VALIDATOR_INDEPENDENCE.json

traceability/
  COVERAGE_GRAPH_V2.json
  REQUIREMENT_CLOSURE_MATRIX.json
  PLATFORM_GENERALITY_REPORT.json

applicability/
  OBLIGATION_APPLICABILITY_INDEX.json

authorization_contracts/
  AUTHORIZATION_BUNDLE_SCHEMA.json
  AUTHORIZATION_BUNDLE_MANIFEST.json
  AUTHORIZATION_READINESS_CONTRACT.json
  HUMAN_RISK_SUMMARY_SCHEMA.json
  AUTOMATIC_RECOVERY_POLICY.json
  AUTHORIZATION_CONSUMPTION_RECEIPT_SCHEMA.json

intent_contracts/
  INTENT_HYPOTHESIS_SET.json
  DECISION_LEDGER.json
  CLARIFICATION_PLAN.json
  COUNTEREXAMPLE_CATALOG.json

policy_contracts/
  CHARTER_POLICY_IR.json
  POLICY_BUNDLE_MANIFEST.json
  POLICY_TEST_MATRIX.json
  POLICY_DECISION_RECEIPT_SCHEMA.json

portability/
  RESOURCE_URI_MAP.json
  ENVIRONMENT_CONTRACT.json
  TOOLCHAIN_LOCK.json
  PLUGIN_MCP_MANIFEST.json
  PORTABILITY_MATRIX.json

control_domains/
  PROJECT_TOPOLOGY_PROFILE.json
  CONTROL_DOMAIN_MATRIX.json
  COMMON_MODE_RISK_ASSESSMENT.json

recovery/
  CHECKPOINT_CONTRACT.json
  RESUME_CAPSULE_SCHEMA.json
  BUDGET_GOVERNOR_POLICY.json
  REVIEW_ROUTER_POLICY.json
```

目录结构是能力全集。每个 Program 只物化适用合同；`OBLIGATION_APPLICABILITY_INDEX.json` 必须为每类合同记录 `APPLICABLE` 或带 Atom 依据的 `NOT_APPLICABLE`。禁止为了满足模板而生成没有 Requirement 来源的空壳 Runtime、Oracle 或 Fixture。

为避免再制造一组平行制品，案例影响、Core Extension Point、Case-to-Core Promotion、Canary Property Matrix与Case Ablation统一写入`PLATFORM_GENERALITY_REPORT.json`；控制流变化复用Architecture目录中的一个`CONTROL_FLOW_DELTA.json`。两者都是现有Architecture Lock和平台通用性审计的只读输出，不创建新的运行链或独立工程。Target Program不因缺少领域案例而生成案例制品；平台Release才汇总跨Profile证据。

`AUTHORIZATION_BUNDLE_MANIFEST.json` 必须使用冻结的 Canonicalization Version，按规范化相对路径排序，并为每项记录 `path`、`size`、`sha256`、`purpose` 和 `required_at_phase`。Bundle Root 是该 Manifest 规范字节的 Hash；它是子项闭包的总索引，不是对子项 Hash、可读权限摘要或独立验证的替代。

上述新增 Manifest 也必须进入相同 Hash 闭包。README 是人类入口，但机器不得从 README 自由文本猜测环境或权限；README 中的安装步骤、插件版本和验证命令必须能追溯到对应机器可读合同。

## 17. 正规执行与自动推进

v2.9 继续保持准备、授权、执行、验证和晋级分离，但“分离”不等于“每个 DAG Node 都要求用户手工确认”。

工程交付链推荐三个 Bundle 里程碑。每个里程碑内部由 Driver 在固定命令、固定权限、固定预算和固定停止门内执行 `advance-until-gate`：

### 17.1 `REPAIR_AND_LOCAL_CLOSURE`

允许：

- Requirement、Schema 和接口实现；
- Main 本地构建；
- Deterministic Oracle；
- External Lab Checker；
- Fake Launcher 单元测试；
- 本地闭环。

不得：

- Artifact Release；
- 认证；
- 真实目标安装。

### 17.2 `RELEASE_BUILD`

允许：

- P4 Input Lock；
- Pack；
- Linkage A/B/C；
- Immutable Artifact；
- Installability；
- Release Candidate Lock。

前提：

- 所有 Requirement 已绑定其 `verification_obligations[]` 所需证据；只有声明 Runtime 的 Atom 才要求 Runtime Proof，只有声明输出语义的 Atom 才要求领域 Oracle；
- 不能仅凭本地自测进入 Release。

### 17.3 `CERTIFY_TO_LOCK`

允许：

- 新认证环境；
- 真实 Executor 正向矩阵；
- 负向和篡改测试；
- Linkage D；
- C4；
- Certificate；
- Certified Release Lock。

前提：

- 每个声明 `real_execution_required=true` 的 Executor 均至少有一次与冻结合同一致的真实 Runtime Evidence；Provider 完全由 Target Profile 决定，平台不得固定任何 Provider；
- 每个 `OUTPUT_SEMANTICS` Atom 的独立领域 Oracle PASS；
- 每个声明 `DETERMINISTIC_RECOMPUTATION` 义务的 Atom 对应 Oracle PASS；
- 纯结构型 Program 不被强制要求真实 Executor、语义 Oracle或 Runtime Topology；
- Artifact 与测试对象一致。

### 17.4 Authorization Bundle 与人工确认

每个里程碑在请求用户授权前生成：

```text
AUTHORIZATION_BUNDLE_MANIFEST.json
AUTHORIZATION_READINESS_RESULT.json
HUMAN_RISK_SUMMARY.json
EXECUTION_AUTHORIZATION_DRAFT.json
```

用户界面展示：本次目标、允许写入位置、是否联网/外发、是否触碰真实目标、最大 attempt、最大时长、停止门及相对上一授权的风险变化。用户只需确认：

```text
milestone_id + authorization_bundle_root_sha256
```

或确认与二者绑定的短挑战口令。所有子 Hash 仍由 Materializer 和 Driver 从 Bundle Manifest 逐项复算。禁止要求用户把几十个子 Hash 当作人工输入，也禁止只展示 Root Hash 而隐藏权限摘要。

### 17.5 哪些步骤自动推进，哪些必须人工

| 情况 | 默认处理 |
|---|---|
| 同一 Driver/Executor/Validator/Schema Hash，下一个 DAG Node 仍在授权集合内 | 自动推进 |
| 相同命令的暂时性失败，未产生未知副作用且仍在 retry budget 内 | 自动重试 |
| 只读复验、结果收口、Receipt 生成已在 Bundle 中明确授权 | 自动推进 |
| Target workspace 内的限定修复，写入路径和 repair budget 已冻结 | 自动推进 |
| Driver、Executor、Validator、Schema 或权限配置变化 | 新 Bundle + 人工授权 |
| 新增网络、私有数据外发、Provider 或本地读取根 | 新 Bundle + 人工授权 |
| 真实目标安装/升级、回滚、删除保留版本 | 独立人工授权 |
| waiver、P3 N/A、降低 Oracle/测试强度 | 独立人工决策 |
| Git 发布或外部发布 | 独立人工授权 |
| 预算即将或已经耗尽，但 State 唯一且无未知副作用 | 提交 `BUDGET_CHECKPOINT_READY` + Resume Capsule；只有加预算或变更范围才请求人工 |
| Hash/State 漂移、未知副作用、策略冲突或状态不唯一 | Fail-closed，返回人工门 |

这意味着 v2.9 通常保留以下真正有风险价值的人工决策：

1. Repair/Local Closure；
2. Release Build；
3. Certify to Lock；
4. Real Target Upgrade；
5. Git/External Publish。

安装后的只读 Receipt 与 Active Manifest 可以在 Real Target Upgrade Bundle 中作为条件式收口步骤预先声明：只有安装和独立验证 PASS 时才自动执行；若其权限或声明范围不同，则仍使用独立 Bundle。

### 17.6 限定自动恢复

`AUTOMATIC_RECOVERY_POLICY.json` 必须区分：

- `TRANSIENT_RETRY`：命令和执行机制不变，可自动；
- `TARGET_SCOPE_REPAIR`：只修改已授权 workspace，可在固定轮数内自动；
- `RESULT_FINALIZATION_ONLY`：不重跑副作用命令，只收口既有结果；
- `CONTROL_PLANE_CHANGE`：Driver/Executor/Validator/Schema/权限变化，必须重新授权；
- `UNKNOWN_SIDE_EFFECT`：禁止自动恢复。

并新增：

- `PLANNED_BUDGET_CHECKPOINT`：提交已完成节点和 Resume Capsule，不把上下文耗尽伪装成业务失败；
- `STALE_AUTHORIZATION_ON_RESUME`：恢复前重新校验授权、Artifact、环境、权限和策略版本，漂移则生成新 Bundle；
- `COST_CASCADE`：先使用确定性检查，再按任务难度和不确定性选择模型/Agent，只有高风险分歧才升级到更昂贵验证或人工判断。

因此，v2.9 减少人工门的主要手段不是允许代理静默修改控制面，而是把常见的路径、Schema、自 Hash、序列化、权限、CLI 和退出语义问题前移到 Authorization Readiness Preflight，在用户授权前一次性发现。

### 17.7 为什么里程碑之间仍要停

三个工程里程碑之间仍必须等待新产生的 Artifact、Result、C4 和 Certificate Hash，因为后一阶段需要绑定前一阶段尚未存在的对象。Driver 可以自动生成下一阶段的 Draft 和可读风险摘要，但不得替用户作出批准决定或伪造用户确认。

该停顿保护的是“是否把新产生的对象带入更高风险阶段”，而不是让用户再次人工校验每个子 Hash。子 Hash 校验始终由机器完成。

## 18. 跨领域Golden Canary

Canary按“平台性质”组织，不按完整业务故事组织。v2.9 Release至少覆盖以下互斥Profile：

| Canary Profile | 目的 | 必须证明 |
|---|---|---|
| `STRUCTURAL_ONLY` | 纯Schema/文件/Hash要求 | 不创建语义Oracle，不要求真实Runtime |
| `BEHAVIORAL_NON_LLM` | 本地确定性CLI或服务行为 | Runtime Evidence不依赖语义模型或多Lane |
| `SEMANTIC_STRUCTURED_OUTPUT` | 结构化领域结果一致性 | Independent Oracle可处理非生成式Artifact |
| `SEMANTIC_GENERATIVE_PORTFOLIO` | 复杂语义与集合级差异 | 模板伪差异、Executor缺失和自报PASS被拒绝 |

平台通用性测试必须：

1. 用不同Target Profile生成相同Core Schema，差异只存在于Profile数据；
2. 改名Provider、Artifact字段、数量、Topology和阈值后仍能编译和验证；
3. 扫描Core，禁止基于任何Target产品名、领域字段、固定数量或固定拓扑进行条件分支；
4. 证明`NOT_APPLICABLE`合法：未声明Runtime/语义义务的Atom不生成多余门禁；
5. 完全移除所有来源Case/Fixture后，Core规范化Hash和路由不变；
6. 换入非来源Profile后，案例专属策略不会进入平台控制流。

具体来源案例的正向、负向、篡改和Target验收矩阵只保存在`SOURCE_CASE_001`非规范文件中。

## 19. 测试策略

### 19.1 Factory 单元测试

- 正交 Requirement Classification Schema；
- Evidence Compatibility；
- Oracle Coverage；
- Coverage Graph v2；
- Executor Role 分离；
- Freeze 前硬停止；
- Finding 稳定性；
- Platform/Profile 分层；
- Capability/Behavior分解与Architecture Candidate稳定性；
- Stage/Subharness/Module/Semantic Slot分类和解释；
- Rule/Policy/Heuristic/Capability/Oracle分离；
- Architecture Lock与Requirement Reopen边界；
- Production-first Finding和Repair顺序；
- 领域词和固定参数硬编码审计；
- 单一案例只能形成Candidate Finding，不能直接改变Core；
- Target Profile加载前后Core状态机、Gate、CLI和Extension Point集合相同；
- Control Flow Delta区分新增、替换和删除，并优先复用现有节点；
- `STRUCTURAL_ONLY` 不被强制生成 Runtime/Oracle；
- SQLite CAS 与 Idempotency。

### 19.2 编译器测试

- 新制品全部生成；
- Architecture Decision IR先于Workpack/Evidence编译；
- Architecture-to-Run正向/反向追踪；
- Typed Interface、State Owner、Tool/Rule/Policy Binding完整；
- 确定性Controller拥有控制流，Semantic Slot不能创建工具/Stage；
- 编译器在Case/Fixture目录完全不可用时仍能生成相同Core Schema和路由；
- Profile中的未知控制流字段Fail-closed，不能动态创建平台分支；
- Hash 和反向引用完整；
- 缺失 Oracle 时拒绝候选；
- `OUTPUT_SEMANTICS` Atom 不得只绑定结构 Validator；
- v2.8 Compatibility Reader。

### 19.3 Validator 测试

- 自报 PASS 不被信任；
- Raw Output 独立重算；
- 共享判定实现被拒绝；
- Fake/Real Executor 边界；
- Runtime Topology；
- Input/Output Lineage；
- Negative/Tamper Coverage。
- Validator-only Repair不能关闭Production Finding；
- Prompt-only隐性Rule被拒绝；
- 同Chat多CLI最高只能产生`COORDINATED_SEPARATION`结果；
- 父Coordinator改写Lab Result或选择性丢弃分歧时失败。

### 19.4 E2E 测试

```text
Requirement Intake
→ Clarification
→ Requirement Readback and Freeze
→ Capability and Behavior Decomposition
→ Architecture Proposal and Clarification
→ Architecture Readback and Lock
→ Rule/Policy/Run Contract Compilation
→ Evidence and Oracle Completion
→ Candidate
→ Runtime Handoff
→ Main
→ External Lab
→ Linkage
→ Certification
```

必须同时包含成功链与预期失败链。

E2E至少分别运行`STRUCTURAL_ONLY`、`BEHAVIORAL_NON_LLM`、`SEMANTIC_STRUCTURED_OUTPUT`和`SEMANTIC_GENERATIVE_PORTFOLIO`，不得只用来源案例Fixture验证平台。

还必须执行两类去偏置测试：

1. **Case Ablation**：完全移除来源Profile、正文案例与Fixture后，Core Schema、Gate、状态机、CLI、Extension Point和通用路由的规范化Hash不变；
2. **Case Substitution**：换入不同业务领域的Target Profile，只允许Profile数据、领域Rule、工具绑定和Oracle改变，平台控制流不得随案例叙事转向。

### 19.5 Authorization Bundle 与交互测试

- Root Hash 任一子项变化后必须变化；
- Manifest 顺序、路径规范化和 Canonicalization Version 可跨进程复算；
- 用户确认一个 Bundle Root 后，Materializer 必须逐项验证全部子 Hash；
- 人工可读风险摘要与机器权限字段不一致时必须失败；
- Readiness 未 PASS 时不得展示可消费授权；
- 同范围自动推进不得产生逐节点人工门；
- Driver/Executor/Validator/Schema/权限/外发变化必须要求新 Bundle；
- 旧授权重复消费、过期、State Hash 漂移和 Bundle 替换全部失败；
- UI/Chat 测试证明用户无需复制原始子 Hash 列表；
- 当前失败发生在副作用前时，必须留下结构化 blocker 而不创建伪 attempt。

## 20. 迁移方案

### 20.1 隔离原则

不得原地改写 v2.8 normative package。建议建立：

```text
Harness_Foundry_v2_9/
  Harness_Foundry_v2_9_Start_Package/
  Harness_Foundry_v2_9_Chat_Factory/
  Harness_Foundry_v2_9_Execution_Runtime/
  Harness_Foundry_v2_9_External_Lab/
  Harness_Foundry_v2_9_Linkage/
```

也可以把上列目录拆成独立 sibling repositories；无论采用 monorepo 还是多仓，v2.9 根都必须位于 v2.8 根之外，并拥有新的 Git 边界、Program ID、SQLite、Output/State Root、锁文件、权限和证书链。当前 v2.8 工作树存在进行中变更时，禁止直接复制工作树作为 v2.9 基线；只能从已确认的 commit/spec lock 或显式文件 allowlist 导入，并为每个导入字节记录 Hash。

v2.8 保持：

- 只读；
- 原 Hash；
- 原 SQLite；
- 原 Program；
- 原证书与回执；
- 原 Git 历史。

v2.9 对 v2.8 的访问只能是受清单约束的只读导入。禁止共享 SQLite、lock、PID/lease、缓存、执行输出、证书目录、Git index、虚拟环境或默认端口。`V2_8_BASELINE_IMPORT_MANIFEST.json` 至少记录来源 commit、Spec Hash、文件清单、排除项、新目标根和 `writes_to_v2_8=0`；独立检查必须证明 v2.8 Tree Hash、状态库 mtime 和运行中项目均未变化。

### 20.2 Schema 与状态迁移映射

迁移不是在 v2.8 SQLite 上执行 `ALTER/UPDATE`。v2.9 必须创建新 Program、新 `runs/<v2_9_program_id>/factory.sqlite3`，把 v2.8 IR/证据作为带 Hash 的只读 Import Source。

| v2.8 字段/对象 | v2.9 初始映射 | 自动映射边界 |
|---|---|---|
| `atom_id`、Source Locator、原文 | 原值保留并记录 `import_source_hash` | 可自动 |
| `verification_mode` | 保留到 `legacy_verification_mode` | 不得自动推导全部新义务 |
| `owner` | 候选 `producer_owner` | 不得自动推导独立 Validator |
| `coverage_edges` | `legacy_routing_edges` | 不得自动升级为履约边 |
| `negative_cases` | `declared_fixture_candidates` | 无 executable/hash/expected finding 时不得标为可执行 |
| Target 中的 Executor 描述 | `unatomized_target_claims[]` | 必须澄清或补 Atom |
| v2.8 PASS/Certificate | `historical_evidence_refs[]` | 只作历史证据，不映射 v2.9 PASS |
| 缺少新分类字段 | `classification_status=UNCLASSIFIED` | 阻止 Readback/Freeze |

状态映射必须 Fail-closed：

| v2.8 状态 | v2.9 Import 后状态 | 原因 |
|---|---|---|
| `CLARIFYING_REQUIREMENTS` | `WAITING_REQUIREMENT_TYPE_COMPLETION` | 新分类尚未完成 |
| `READY_FOR_READBACK` | `WAITING_REQUIREMENT_TYPE_COMPLETION` | 旧 Readback 不包含新合同 |
| `REQUIREMENTS_FROZEN` | `WAITING_REQUIREMENT_TYPE_COMPLETION` | 旧 Freeze 不自动继承 |
| `START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW` | `IMPORTED_V2_8_BASELINE_REQUIRES_RECLASSIFICATION` | Candidate 只作只读输入 |
| 下游 PASS/Certificate | `HISTORICAL_EVIDENCE_IMPORTED_NOT_V2_9_CLOSED` | 禁止证书自动升级 |

Import Receipt 至少包含：旧 Program ID、旧 State Hash、旧 IR Hash、旧 Candidate Hash、旧 Spec Lock Hash、新 Program ID、Importer Version、导入时间和 `writes_to_v2_8=0`。

### 20.3 Phase 0：基线冻结

输出：

- v2.8 Spec Lock；
- Factory Tree Hash；
- Test Baseline；
- 已知限制清单；
- source-case Finding 清单。
- v2.8 进行中 Program、运行进程、端口、SQLite/lock 和 Output Root 冲突清单；
- `V2_8_BASELINE_IMPORT_MANIFEST.json` 与导入 allowlist；
- 新 v2.9 根的写入边界和“零回写 v2.8”探针。

### 20.4 Phase 1：v2.9 规范包

实现：

- 正交 Requirement Classification；
- Evidence Obligation；
- Oracle Contract；
- Coverage Graph v2；
- Runtime Topology；
- Validator Independence；
- 新 Schema 和规范文档。
- Authorization Bundle、Readiness、Human Risk Summary 与 Automatic Recovery Policy 合同。
- Expert Intent、Executable Charter、Durable Checkpoint、Control Domain 和 Portability 合同；
- Capability/Behavior、Architecture Decision、Stage/Subharness/Module/Semantic Slot和Deterministic Run Contract；
- Rule/Policy/Heuristic/Target Capability/Oracle分层、来源、冲突和Architecture Binding合同；
- 项目拓扑由 Risk/Target Profile 编译，不把仓库数量写死为平台常量。

### 20.5 Phase 2：v2.9 Chat Factory

实现：

- 新 Intake Questions；
- 新状态门；
- 新 CLI Audit；
- 编译器；
- Validator；
- SQLite Migration Reader；
- Candidate Generation。
- Authorization Bundle Contract 编译、风险摘要生成和只读解释命令；Factory 仍不得授予下游执行权限。
- Intent Hypothesis、Decision Delta、EVPI/Question Cost 排序、反例模拟与高关键歧义门；
- Requirement Freeze后的Architecture Design Epoch、1–3个候选、设计补全问题、Architecture Readback/Lock和Reopen路由；
- Production-first Root Cause分类、Repair顺序、Stage/Subharness/Module选择解释和Architecture-to-Run编译；
- Policy IR 候选与策略测试生成；Factory 不成为运行时 Policy Decision Point。

### 20.6 Phase 3：v2.9 Execution Runtime

实现：

- Runtime Proof 验证；
- External Oracle 调度；
- Evidence Compatibility；
- Semantic Closure；
- 三里程碑 `advance-until-gate`；
- Canonical Authorization Bundle 与 Root Hash 校验；
- 授权前 Readiness Preflight；
- 风险分级人工门与限定自动恢复；
- 一次性消费、State CAS 和子 Hash 闭包验证。
- 事件溯源、幂等 Activity、lease/heartbeat、Checkpoint、Resume Capsule 和 Budget Governor；
- Tool/State Policy Enforcement Point、Decision Receipt 与恢复时 TOCTOU 复验。
- 确定性Controller持有循环/分支/Stage/预算/重试/停止，LLM只执行Typed Semantic Decision Slot；
- 同Chat运行按`COORDINATED_SEPARATION`隔离，外部L3/L4控制域承担最终独立Certificate。

### 20.7 Phase 4：跨领域 Canary

依次运行：

1. `STRUCTURAL_ONLY`，证明平台不会把语义/Runtime 控制强加给无关项目；
2. `BEHAVIORAL_NON_LLM`，证明Runtime Evidence不依赖语义模型或多Worker拓扑；
3. `SEMANTIC_STRUCTURED_OUTPUT`，证明Oracle Contract可处理非生成式领域Artifact，不依赖生成式集合或内部表示；
4. `SEMANTIC_GENERATIVE_PORTFOLIO`，证明集合级语义要求、真实Executor和独立重算可以由Profile声明而不改变Core。

任一 Profile 只有通过 Target-specific 分支或平台硬编码才能成功时，Phase 4 失败。

### 20.8 Phase 5：Foundry v2.9 Release

完成：

- Source Release；
- External Lab；
- Linkage；
- C4；
- Conformance Certificate；
- Certified Release Lock；
- 独立 Git 发布授权。
- 干净 Git clone、随机路径、不同用户名、声明 OS/架构的 Portability Matrix；
- README/Environment/Tool/Plugin Manifest、SBOM、来源证明和发行 Artifact 摘要。

## 21. 兼容策略

### 21.1 推荐策略

采用“可读取、不静默升级”：

- v2.9 可以读取 v2.8 Requirement IR；
- v2.8 Atom 默认标记为 `classification_status=UNCLASSIFIED`，原 `verification_mode` 只保存为 Legacy Source；
- 必须完成人工或规则辅助分类；
- 必须补齐 Oracle 和 Evidence Obligation；
- 未补齐前不得声称 v2.9 合规；
- 不自动修改原 Start Package；
- 生成新的 v2.9 Program 和 Hash。

### 21.2 禁止策略

禁止：

- 将 v2.8 PASS 自动映射为 v2.9 PASS；
- 将旧 Certificate 自动升级；
- 把旧结构验证当作新语义验证；
- 复用旧 Authorization；
- 在原 SQLite 中修改历史 Epoch。

## 22. 验收标准

### 22.1 平台级发布验收

Foundry v2.9 平台只有满足以下条件才可发布：

1. 100% Atom 为 `classification_status=CLASSIFIED`，且三个正交数组非空；
2. 100% `RUNTIME_BEHAVIOR` Atom 具有与其 Executor Profile 一致的 Runtime Evidence Obligation；
3. 100% `OUTPUT_SEMANTICS` Atom 具有 Target Profile 提供的 Independent Oracle；
4. 100% 关键 Atom 具有 Negative Case，认证关键路径具有 Tamper Case；
5. 自报指标不能独立关闭 Requirement，Linkage PASS 不能替代 Semantic PASS；
6. Fake Launcher 不能独立完成声明真实 Executor 的认证；
7. Real Executor Requirement 必须有真实运行回执；未声明真实 Executor 的项目不得被强制执行；
8. Coverage Graph v2 正向与反向绑定完整，缺失任一关键边时 Freeze 失败；
9. `STRUCTURAL_ONLY`、`BEHAVIORAL_NON_LLM`、`SEMANTIC_STRUCTURED_OUTPUT` 和 `SEMANTIC_GENERATIVE_PORTFOLIO` 四类 Canary 全部通过；
10. `audit-platform-generality` 证明平台核心没有 Target 产品名、Provider、Artifact 字段、固定数量、Topology 或阈值硬编码；
11. 改名 Provider、Artifact 和字段并改变数量/Topology 后，平台仍依据 Profile 正确编译与验证；
12. `NOT_APPLICABLE` 路径通过：纯结构项目不生成 Runtime/语义门；
13. Factory 仍停在 `START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW`；
14. Factory 不执行 Workpack、不安装目标、不签发执行授权；
15. v2.8 树、Program、SQLite、证书和回执保持不变；
16. 所有测试、Spec Lock、Skill Validation 和 Git Hygiene 检查通过；
17. 每个执行里程碑均能生成 Canonical Authorization Bundle，Root Hash 与全部子项闭包可由独立进程复算；
18. 人工确认界面只要求一个 Bundle Root/短挑战口令，同时完整展示权限、外发、真实目标、预算和停止门摘要；
19. Readiness 未 PASS、摘要与权限不一致或子 Hash 漂移时不得物化可消费授权；
20. 同范围 `advance-until-gate` 不产生逐节点人工确认，限定重试不会扩大写入或权限范围；
21. Driver、Executor、Validator、Schema、权限、外发或真实目标变化会返回新人工门；
22. Factory 只编译 Bundle Contract，实际授权由独立 Runtime 在后续用户确认后物化。
23. v2.9 位于独立新根，v2.8 Tree Hash、Program、SQLite、运行锁、输出和证书链均未被写入或复用；
24. 每条关键宪章条款均能从 Clause ID 追溯到 Policy Decision、Enforcement Point、Receipt 和策略测试；
25. 高关键歧义、冲突和无来源假设未关闭时无法 Freeze，且系统能解释为什么下一问题比其他问题更值得问；
26. 预算耗尽且无未知副作用时生成可验证 Resume Capsule；恢复前会拒绝过期授权、Artifact/环境/策略漂移和非幂等重复执行；
27. GitHub 发行物中不存在本机绝对路径、越界相对引用、外部 symlink、隐式同级仓库或未声明工具/插件；
28. README 与机器可读 Environment/Toolchain/Plugin Manifest 一致，干净 clone 在随机路径、不同用户名和声明平台矩阵中可启动并验证；
29. Main、Lab、Linkage 的独立性按向量而非 CLI 数量评估，高风险认证至少隔离任务上下文、workspace、状态、凭据/签名与 Validator 实现；
30. 多 Agent/多 CLI 的共同失效测试能拒绝共享错误 Oracle、自我认证和同一父任务伪独立；
31. 发布包含锁文件、SBOM 和可验证的来源/构建证明；Secret 只通过声明的注入机制提供且不进入仓库。
32. 100% Blocking/High Capability 从 Requirement 追踪到 Architecture Decision、Stage/Subharness/Module、Run Transition 和实际生产输出；
33. 每个 Stage/Subharness/Module 均有明确选择理由、Typed Interface、State Owner、Allowed Tools、Rule/Policy集合、预算和Return Path；
34. 循环、分支、停止、重试和工具权限由确定性Controller持有；LLM只能在冻结的Semantic Decision Slot内返回Schema约束候选；
35. Domain Rule、Governance Policy、Heuristic、Target Capability Constraint和Oracle Rule可以分别枚举并检查来源，关键规则不存在Prompt-only隐藏状态；
36. 任何Production Finding不得由Validator-only Repair关闭；修复后必须先证明Producer直接行为改变，再更新Oracle和回归矩阵；
37. 同一Codex Chat产生的多CLI/Subagent结果标记为`COORDINATED_SEPARATION`，最终独立证书来自上下文、身份、Signer和发布权独立的控制域；
38. 至少一个非来源案例 Canary能根据输入自动提出Architecture候选、解释Stage/Subharness/Module选择并暴露缺失设计问题，而不是只生成验证合同。
39. Normative Core、Target Profile与Case/Fixture物理分层，依赖只能由案例指向Profile再指向Core Extension Point，Core不得反向读取案例；
40. 禁用全部来源案例后，Core Schema、Gate、状态机、CLI、Extension Point与通用路由的规范化Hash保持不变；
41. 单一案例不会直接产生平台默认Rule或新控制节点；所有Case-to-Core晋升都有形式化不变量、跨领域复现或安全例外批准；
42. 加载Target Profile不能增加或修改平台State、Gate、CLI、Stage类型、重试和停止语义，未知控制流字段必须Fail-closed；
43. 每次Architecture Lock都有Control Flow Delta；净新增节点说明为何参数化、替换和现有Extension Point均不足，并记录成本、恢复和删除旧路径；
44. Canary Property Matrix证明每个案例只覆盖必要性质，删除重复故事样本不会降低平台性质覆盖。

### 22.2 Target Profile验收边界

Target Profile只能关闭自身声明的领域Requirement，不构成平台默认规则。每个Profile必须证明：

1. 领域Rule、工具、数量、Topology、阈值和Oracle均来自冻结Profile；
2. Profile加载前后Core State、Gate、CLI和Extension Point集合不变；
3. Profile无法通过未知字段动态创建平台控制流；
4. 删除该Profile后，Core规范化Hash和其他Profile行为不变；
5. Profile专属PASS不能被提升为v2.9平台Certified Release。

## 23. 风险与控制

| 风险 | 控制 |
|---|---|
| Evidence 数量继续膨胀 | 使用 Evidence Index、最小必需字段和分层回读 |
| Semantic Oracle 不稳定 | 由 Target Profile 冻结算法、阈值和 Unknown Policy；声明多重 Oracle 时按合同执行 `ALL_OF` |
| Lab 成本过高 | 单元测试可使用 Fake；只有声明真实 Executor 的 Atom 才要求受控真实矩阵 |
| 非确定性 Executor 结果波动 | Target Profile 冻结 Provider 参数、采样/推理配置和完整调用证据 |
| Validator 与实现重新耦合 | 禁止共享最终判定函数，要求独立重算 |
| 来源案例规则渗入平台 | `audit-platform-generality` + 四类跨领域 Canary + Profile 参数来源追溯 |
| v2.8 迁移污染 | 新目录、新 Program、新 SQLite、新 Spec Epoch |
| 自动推进越权 | 包内自动推进，包间等待 Hash 绑定人工授权 |
| Hash 被误认为正确性 | Evidence Compatibility Gate 明确区分身份与语义 |
| 单一 Root Hash 隐藏实际权限 | 强制 `HUMAN_RISK_SUMMARY` 与机器权限字段双向一致并可展开查看子项 |
| 用户仍需复制大量子 Hash | Chat/UI 只接收 Bundle Root 或短挑战口令，子 Hash 由机器复算 |
| 授权后立即因静态错误失败 | 授权挑战前强制无副作用 Readiness Preflight |
| 自动恢复静默修改控制面 | `CONTROL_PLANE_CHANGE` 必须生成新 Bundle 并重新人工授权 |
| 人工门过多形成排队 | 以风险增量决定人工门，同范围节点由 `advance-until-gate` 连续执行 |
| 宪章只存在于自然语言导致执行不一致 | Charter Clause 编译为 Policy IR，在工具/状态边界执行并留 Decision Receipt；不可形式化项保留显式人工门 |
| 长任务因上下文、进程或预算耗尽中断 | 事件溯源、Checkpoint、Resume Capsule、幂等键、lease/heartbeat 与恢复前 TOCTOU 复验 |
| 多 Agent/多 CLI 产生共同失效 | 独立性向量、确定性 Oracle、异构 Validator、独立权限/签名、盲测和不可变 Artifact Handoff |
| GitHub 包只能在作者电脑运行 | 禁止本机绑定；环境/插件 Manifest、lockfile、clean-clone 矩阵、SBOM 与 Provenance Gate |
| 问太多问题造成高成本和疲劳 | 按不确定性、风险、EVPI 与问题成本排序；批量询问高价值问题，低风险假设显式暂存而不静默确认 |
| 为提升稳定性无限增加工程 | 使用 Capability Plane 与 Risk Profile 编译拓扑；项目数量不是质量指标，职责和独立性才是 |
| 提案持续增加校验但Producer逻辑不变 | 强制Production-first Root Cause Plane和Repair Order；Architecture/Rule/Controller未修复时Validator增强只能标记为防扩散措施 |
| LLM自由决定循环、分支和停止导致漂移 | 确定性Controller拥有控制流，LLM只进入Typed Semantic Decision Slot |
| Stage/Subharness/Module凭感觉拆分 | 依据状态所有权、局部循环、失败隔离、工具集和复用性编译并解释选择 |
| 领域逻辑继续隐藏在Prompt/知识库 | Rule Provenance Ledger + Rule/Policy/Heuristic/Capability/Oracle分类与冲突顺序 |
| 同Chat多CLI被误当作独立验证 | 只授予`COORDINATED_SEPARATION`；认证级Claim要求外部顶层运行、独立Signer和不可变交接 |
| 首个案例在文字和实现中锚定升级方向 | Core/Profile/Case物理分层、Platform Generality Report、跨领域晋升门与Case Ablation |
| 每个新案例都追加策略、Stage或Subharness | Profile只能填写Extension Point；Control Flow Delta优先参数化、替换和复用，净新增需Architecture Reopen |
| 为已知失败样本过拟合而失去未知领域通用性 | Canary按性质最小化，执行Case Substitution与非来源Profile复现，不把Fixture作为设计输入 |

## 24. 来源证据与现行规范分离

案例现场证据、历史Artifact、只读重算、Target专属Finding、正负向/篡改Fixture与候选生产拓扑已移至`SOURCE_CASE_001`非规范文档；R6完整原文另存为`HISTORICAL_NON_NORMATIVE_ARCHIVE`。

主文档只保留：

- 已抽象的问题类型；
- 能够跨领域表达的Core合同；
- Case-to-Core Promotion条件；
- Case Ablation与Case Substitution验收；
- 对实现、迁移、发布和认证状态的非声明。

来源案例的路径存在、历史PASS或聊天结论都不能成为当前v2.9实现事实。若未来需要把案例观察晋升为Core规则，必须在`PLATFORM_GENERALITY_REPORT.json`中记录形式化不变量、非来源Profile复现或安全例外批准。

## 25. 建议实施顺序

```text
1. 冻结 v2.8 已确认 commit/spec lock，并登记运行中项目、状态库、锁和输出冲突面
2. 在 v2.8 根之外建立 v2.9 新根、新 Git、新 Program/SQLite/State/Output Root，并验证零回写
3. 通过 Import Manifest/allowlist 导入基线；不得复制当前脏工作树、runs、cache、证书或本地环境
4. 先物理分离Normative Core、Target Profile和Case/Fixture，并在Platform Generality Report中冻结Core Extension Point Index
5. 将来源案例只登记为Case Finding与Profile输入，不允许其参与Core Schema和控制流编译
6. 编写 Expert Intent、Requirement和Architecture Design Epoch Schema
7. 实现Capability/Behavior分解、Architecture Candidate、Stage/Subharness/Module分类与Architecture Lock
8. 编写Domain Rule、Governance Policy、Heuristic、Target Capability和Oracle Rule分层合同
9. 编写Deterministic Run Contract、Semantic Decision Slot、Typed Interface、Architecture-to-Run Traceability和Control Flow Delta
10. 编写Evidence/Oracle、Authorization、Readiness、Human Risk、Review Router、Budget Governor与Recovery Schema
11. 编写Portability、Environment、Toolchain、Plugin/MCP、Control Domain与Project Topology Schema
12. 实现Production-first Finding/Repair Router和Factory Audit Gates
13. 实现v2.9 Candidate Compiler；Factory只生成架构、候选和合同
14. 先在禁用全部Case输入时完成Core编译、单元测试和Case Ablation基线
15. 实现独立Runtime的确定性Controller、Policy Enforcement、Bundle Materializer、State CAS、事件日志、Checkpoint与advance-until-gate
16. 实现独立Lab/Linkage Artifact Envelope、签名和共同失效审计
17. 运行Producer架构、Rule、Controller、模块行为和直接输出回归，再运行Evidence/Oracle测试
18. 运行Authorization Readiness、自Hash、序列化、权限、预算、幂等、恢复与TOCTOU负向测试
19. 运行STRUCTURAL_ONLY / BEHAVIORAL_NON_LLM / SEMANTIC_STRUCTURED_OUTPUT生产架构Canary和Case Substitution
20. 最后加载一个来源案例Target Profile，运行隐性Rule提取、架构候选、生产行为和Oracle Canary
21. 注入单案例晋升、Profile修改Core、未预算控制流、缺失生产路径、LLM自由控制流、Validator-only Repair和伪多CLI独立性
22. 验证高价值澄清、Architecture Readback/Lock、Production-first Repair和同ChatClaim降级
23. 验证同范围自动推进、预算检查点、断点恢复、控制面变化重授权、真实目标与Git独立门
24. 执行clean-clone、随机路径、不同用户名、无同级仓库、缺失插件和声明OS/架构矩阵
25. 运行audit-platform-generality / audit-portability / audit-control-domain-independence / audit-architecture-run-traceability
26. 完成Runtime、External Lab、Linkage、Certification、SBOM和Provenance
27. 签发v2.9 Certified Release Lock
28. 独立授权Git发布
```

## 26. 最终原则

Foundry v2.9 的核心判断应当是：

> Foundry 不必自己判断目标领域产出是否优秀，但必须保证任何“行为或语义合规”结论都由该 Target Profile 要求的真实运行、独立计算、对抗测试和可追溯证据共同支撑。

在此之前还必须满足：Foundry先把冻结需求编译成可解释的生产架构、规则分层和确定性Run Contract。Verification证明生产逻辑被执行，不能替代生产逻辑本身。

同时坚持：

```text
Hash proves identity, not correctness.
Linkage proves continuity, not semantics.
Schema proves shape, not behavior.
Self-report is an input to validation, not independent evidence.
Semantic requirements require semantic oracles.
Platform rules are domain-neutral; domain rules live in Target Profiles.
No target name, provider, artifact shape, count, topology, or threshold is a platform default.
Humans approve risk and scope; machines verify bytes and evidence.
One Bundle Root reduces manual input; it never removes child verification.
Automation proceeds within a fence and stops when the fence changes.
Natural-language charters guide humans; executable policy gates machines.
Three CLI names do not prove three independent control domains.
Durable state lives in events and receipts, not only in chat context.
Portable releases declare every environment and tool binding.
More agents or projects are justified by risk reduction, not by count.
Design the producer before designing the proof.
Fix intent, architecture, rules and control flow before adding validators.
The LLM may reason inside bounded slots; deterministic code owns the run.
Cases discover candidate problems; they do not define the platform.
Profiles fill frozen extension points; they do not mutate core control flow.
Prefer parameterize, replace, or reuse before adding another stage or strategy chain.
```

## 27. 关联文档影响检查

本次授权交互优化与仓库内关联文档的关系如下：

| 文档/入口 | 检查结论 | 本次处理 |
|---|---|---|
| `docs/START_PACKAGE_TRUST_PRINCIPLES_LIMITATIONS_AND_CODEX_THREE_CLI.md` | 已明确 A3 是有围栏自动驾驶、Hash 不证明正确性、真正风险点保留人工门，与本方案一致 | 保持为 v2.8 历史/解释基线，不回写 v2.9 未实现能力 |
| `docs/START_PACKAGE_THREE_PROJECT_ARCHITECTURE_REVIEW.md` | 已指出重型审批和 Evidence 爆炸风险，支持 policy 驱动自动推进 | 保持历史评审不变；本文件补齐 Bundle Root、Readiness 和风险增量规则 |
| `README.md`、`docs/ARCHITECTURE.md`、`docs/CHAT_USAGE.md` | 描述当前可执行的 v2.8 Factory，仍要求精确 Freeze token 和 Authoring Stop | 不修改；v2.9 Proposal 不得伪装成当前能力 |
| `AGENTS.md` 与 `harness-foundry-start-author` Skill | 当前约束明确禁止 Factory 授权、执行 Workpack 或安装目标 | 不修改；只有独立 v2.9 Factory/Runtime 实现并认证后才建立新版本 Skill |
| `repo://harness-foundry-v2.8-start-package` | v2.8 normative input，Hash 和历史 Program 已被下游引用 | 继续只读；v2.9 必须创建新规范包、新 Program、新 SQLite 和新证书链 |

因此，本次需要调整的是 v2.9 升级提案本身的授权合同、状态、门禁、测试和验收设计；当前 v2.8 README、Skill、Factory CLI 和规范包不应随提案一起修改。未来真正实现 v2.9 时，应在新版本工程中同步新增：

1. Authorization Bundle Schema 与 Canonicalization 规范；
2. Bundle Readiness Validator；
3. Human Risk Summary 与单 Root/短口令交互；
4. Execution Runtime Materializer 与 `advance-until-gate`；
5. Automatic Recovery Policy 与风险增量 Gate；
6. 新版文档、Skill、CLI 帮助和迁移说明。
7. Expert Intent、Charter Policy、Checkpoint/Resume、Budget Governor 和 Review Router；
8. Environment/Toolchain/Plugin Manifest、Portability Matrix、SBOM 和 Provenance；
9. Control Domain Matrix、独立性等级和共同失效测试。
10. Capability/Behavior Graph、Architecture Decision IR和Architecture Lock；
11. Stage/Subharness/Module/Semantic Slot分类与Typed Interface；
12. Domain Rule、Policy、Heuristic、Target Capability和Oracle分层目录；
13. Deterministic Run Contract、Production-first Repair Router和同ChatClaim等级。

## 28. 2026-08-03 最新研究复核与落地判断

### 28.1 总结论

当前“Start Package → 执行包 → 校验工程 → 联通测试”的方向仍然正确，但它主要解决四件事：要求被记录、执行有边界、结果被检查、制品身份连续。最新研究和工程实践共同提示，还需补上四个容易被忽略的面：

1. **意图不确定性**：模型能写出代码，不等于它知道什么时候需求含糊、应该问什么；
2. **宪章执行性**：自然语言规则放在上下文里，不能保证每个工具调用和状态迁移都一致遵守；
3. **长任务耐久性**：聊天、进程或预算中断后，必须从已提交状态恢复，而不是靠模型回忆；
4. **共同失效与可移植性**：多个 Agent 可能共享同一种错误；作者电脑能运行也不等于干净 clone 可运行。
5. **生产控制流**：让概率模型同时决定循环、分支、工具和停止会放大漂移；确定性程序应持有控制骨架，模型只承担必要的语义槽位。

通俗地说，v2.8 已经有“施工图、施工单、质检和交接单”，v2.9 还需要：一台每次开闸都按规则判断的门禁机、一套停电后能续工的施工日志、一组不会由同一人自检自签的责任域，以及一份换城市和机器仍能开工的材料/设备清单。

### 28.2 研究成熟度与采用边界

| 方向 | 研究/工程信号 | v2.9 落地判断 |
|---|---|---|
| 按不确定性和问题价值进行澄清 | 2025–2026 的 IntentSim、SAGE-Agent、ConsistentChat 和 ClarifyCodeBench 均指出：强生成能力并不自动带来强歧义发现；结构化问题选择和对话骨架更有效 | **纳入核心**：Intent Hypothesis、EVPI/Question Cost、Decision Delta、反例和高关键歧义门 |
| Durable Workflow | Temporal 等成熟工作流平台已长期采用事件历史、Activity retry、Signal/Update、heartbeat 和恢复机制 | **纳入核心，但不绑定单一产品**：抽象 Durable Runtime Contract，可选择自研或适配器 |
| Policy-as-Code | OPA 等成熟方案将 Policy Decision 与业务执行分离，并提供 Bundle/Decision Log | **纳入核心**：Clause → Policy IR → PDP/PEP → Receipt；自然语言自动形式化仍需独立测试和批准 |
| 多 Agent / 多模型独立验证 | 研究显示错误在模型、架构和 Provider 间仍可能相关；增加 Agent 数量不等于按比例增加可靠性 | **纳入核心**：确定性 Oracle、异构实现、权限/签名隔离和共同失效审计优先于“多开几个 CLI” |
| 更大的 Agent 团队和可靠性记忆 | 2026 年多篇预印本探索小团队+长期记忆、能力信誉和语义 Checkpoint | **研究性 Canary**：可实验，不作为 v2.9 必须依赖的认证基础 |
| 自然语言 Harness 与 OS 级 Agent Checkpoint | 2026 年仍以预印本/研究原型为主 | **不作为核心依赖**：吸收显式合同、Artifact 和恢复思想，先用可审计的文件/事件协议实现 |
| Dev Container / OCI / SLSA / in-toto | 已有公开规范和广泛工程使用 | **纳入发布基线**：环境复现、镜像身份、SBOM 和 Provenance；但容器本身不是完整信任证明 |

对最新论文必须区分证据等级：ACL/EMNLP/NAACL/ICML/TMLR 结果可作为设计依据；2026 年 arXiv/OpenReview 新稿只能作为趋势和实验候选，不应被写成已经普遍证实的生产结论。

## 29. 宪章一致性、人工 Review、中断和成本的终局方案

### 29.1 为什么现有链路仍会不一致

Start Package 和执行包能冻结“应该做什么”，但如果宪章条款只作为长 Prompt 中的文字，真正执行时仍可能发生：

- Agent 忘记前文、错误解释优先级或把建议当授权；
- 工具调用前没有重新查看最新权限、State Hash 和外部世界状态；
- 同一模型既生成实现又解释宪章、验证结果，形成自我确认；
- 每个小节点都停给人看，人在高频确认中逐渐只点通过；
- 预算耗尽被当作通用 STOP，下一次只能重新读上下文和猜执行到了哪里。

所以“再写得更详细”不是终局。终局是把判断拆成三层：

```text
人类可读 Charter
  ↓ 编译 + 测试 + Freeze
Executable Policy Bundle
  ↓ 每次工具调用/状态迁移强制查询
Policy Decision + Enforcement + Receipt
```

### 29.2 Executable Charter

每个关键 Clause 具有稳定 ID，并标注：适用阶段、输入字段、允许/拒绝条件、Unknown Policy、冲突优先级、是否可 waiver、执行点和 Return Path。Policy Decision Point 只回答 `ALLOW / DENY / REQUIRE_HUMAN / UNKNOWN`；Tool Gateway、State Transition Guard 和 Release Gate 才是 Enforcement Point。

Policy 输入必须包含策略真正依赖的世界状态，例如当前 Artifact Hash、目标环境、Secret/Network Scope、授权到期时间和是否已发生副作用。否则会出现“策略文字看起来没问题，但看不到关键事实”的假安全。每次决策输出 Receipt，认证时可以反查“哪条宪章、看到什么输入、为何允许了这一步”。

### 29.3 Review Router：减少人工，但不弱化授权

人工 Review 不按节点数量固定触发，而按以下信号路由：

```text
risk_delta
+ irreversible_or_external_effect
+ policy_unknown
+ intent_uncertainty
+ validator_disagreement
+ common_mode_risk
→ HUMAN / SECOND_ORACLE / AUTO
```

默认自动：确定性 Schema/Hash/Policy PASS、同一 Bundle 内幂等推进、无副作用只读复验、暂时错误重试和已授权范围内修复。

默认人工：新增权限/外发/Secret、真实安装/删除/发布、waiver、未知副作用、策略冲突、高关键需求仍有多种解释，以及 Validator 无法独立消除的分歧。

人工界面只展示增量：本轮新增、改变、失效、仍未决定的事项，以及相对上次授权的风险差异；不要求反复阅读全部历史或复制子 Hash。

### 29.4 Budget Governor 与可恢复 STOP

Budget Governor 为每个阶段冻结 token、时间、外部调用、重试和人工等待预算，并持续估计“完成剩余闭环”的成本。默认级联：

```text
deterministic check
→ low-cost model/tool
→ stronger model or second oracle
→ human only when risk justifies it
```

达到预算边界时不继续消耗，也不丢弃已完成工作，而是原子提交 `RESUME_CAPSULE.json`：

- Program/Node/Attempt 和 State Hash；
- 已提交 Artifact/Receipt/Event 范围；
- 未执行节点和禁止重复的副作用；
- 当前授权 Bundle、有效期和剩余 Scope；
- 环境、工具、策略版本和最后心跳；
- 中断原因、恢复前必查项和建议最小新增预算。

恢复只接受“事件历史 + Artifact + Receipt”，不接受模型声称“我记得做到这里”。若授权、文件、环境或策略漂移，必须生成新 Bundle；若副作用不明确，则由独立 Reconciler 先查外部状态，不能盲目重跑。

### 29.5 结论

“更多人工”与“更多自动化”都不是单独答案。v2.9 应采用：确定性政策执行 + 风险分流 + 有围栏自动推进 + 事件化 Checkpoint + 少量高价值人工决定。这样减少的是重复确认和重启成本，保留的是权限、不可逆风险和无法由证据消除的判断。

## 30. Expert Chat Intention Lock v2

### 30.1 目标用户与交互方式

本模式面向已经知道业务方向、但希望更快暴露缺口和边界的操作者。它不做面向普通用户的逐步教学，而是像一位资深架构评审者：接受简短回答，主动找冲突、缺失前提、负向路径和无法验收的表述。

建议的对话骨架：

1. Outcome、Non-goal 和成功后的可观察变化；
2. 权限、责任人、利益相关方和禁止代替用户决定的事项；
3. 典型场景、边界场景、失败返回和不可逆动作；
4. 数据、环境、工具、插件、网络、Secret 与可移植性；
5. 并发、过期状态、重试、取消、回滚和预算；
6. Oracle、独立性、负向/篡改用例和证书 Claim；
7. 发布、迁移、兼容、观测和退场条件。

### 30.2 不问“固定问题”，而问“最值钱的问题”

系统维护多个可能意图及其证据，不应过早只保留一个解释。每轮将候选问题按以下近似值排序：

```text
question_value
  = ambiguity_reduction
  × criticality
  × downstream_rework_avoided
  - answer_cost
  - interruption_cost
```

一次优先批量提出 3–7 个高价值问题；能由本地证据确定的事实先自行核对，不把查文件的问题丢给用户。区分：

- `SPECIFICATION_UNCERTAINTY`：用户意图确实存在多个可能解释，需要澄清；
- `MODEL_UNCERTAINTY`：证据足够，但当前模型不会或不确定，应换工具/模型/Validator，不能烦用户；
- `WORLD_STATE_UNCERTAINTY`：外部状态可能变化，应读取、探测或返回受控人工门。

### 30.3 Decision Ledger 与每轮差量回读

每条决定标记为：`USER_FACT`、`SOURCE_FACT`、`INFERENCE`、`ASSUMPTION`、`CONFLICT`、`OPEN`、`DEFERRED` 或 `SUPERSEDED`。每轮只回读：

- 新增了什么；
- 哪些决定改变或失效；
- 仍有哪些高关键 Open/Conflict；
- 哪个 Atom、Gate、测试或成本受到影响。

“没有被用户纠正”不能把 `ASSUMPTION` 自动升级为 `USER_FACT`。Freeze 前的硬条件是：没有 Blocking/High 的未决冲突；每个关键约束有来源、示例/反例、Owner、Oracle 和验收路径；所有推断均显式可见。

### 30.4 启发式反例库

Chat 应主动使用但不限于以下启发式：

- **反事实**：如果不允许使用当前模型/插件，目标是否仍成立？
- **边界极值**：输入为空、超大、重复、过期或相互冲突时怎么办？
- **禁止代理**：哪些看似相关指标绝不能代替真实 Requirement？
- **失败返回**：执行了一半失败，回到哪个明确节点？
- **不可逆性**：哪一步会发布、删除、扣费、外发或影响真实用户？
- **共同失效**：Producer 与 Validator 是否复制了同一假设或代码？
- **并发/过期**：授权后状态变化，是否仍允许执行？
- **可移植性**：换用户名、路径、OS、架构或缺失插件会怎样？
- **预算**：当前方案的最小闭环成本和停止/恢复点在哪里？
- **独立 Oracle**：谁可以不相信 Producer 的声明而重新得到结论？

## 31. 跨设备、跨仓库与 GitHub 可发布设计

### 31.1 不依赖本地路径的资源模型

仓库内只保存逻辑身份和仓库相对路径：

```text
repo://platform/schema/requirement-ir
artifact://sha256/<digest>
tool://codex-cli@capability-profile
plugin://vendor/name@version
profile://target/profile-id@version
secret://runtime/credential-name
```

Runtime 在启动时生成或读取本机专用 `LOCAL_BINDINGS.json`，把逻辑 URI 解析为绝对路径、可执行程序和 Credential Provider；该文件进入 `.gitignore`，不是规范输入，也不能出现在 Certificate Claim 中。必须扫描发行树中的绝对路径、`file://`、外部 symlink、越界相对路径和已知用户名。

### 31.2 README 与机器合同的最低内容

每个可独立使用的 Factory/Harness/Validator 仓库必须同时提供：

- 支持的 OS、架构和文件系统限制；
- Python/Node/容器等运行时范围与 lockfile；
- 工具、插件、MCP Server、模型能力和版本/来源；
- 每个绑定是 required 还是 optional，所需权限、网络、认证方式和最小 Scope；
- `.env.example` 或 Secret Provider 指南，永不提交真实 Secret；
- 一条最小 Quickstart、一条只读 health/verify 命令和预期输出；
- 离线、插件缺失、版本不兼容和权限不足时的 fail-closed/降级行为；
- 数据/模型下载、缓存、许可证、成本和清理方式；
- 生成物、运行状态、证据和源码的目录边界；
- SBOM、Provenance、发布签名和漏洞/兼容性说明。

README 不能是唯一真相。`ENVIRONMENT_CONTRACT.json`、`TOOLCHAIN_LOCK.json` 和 `PLUGIN_MCP_MANIFEST.json` 提供机器可读来源，文档校验器检查二者一致。

### 31.3 Clean-clone Portability Matrix

发布前至少验证：

1. 新临时目录和随机路径；
2. 不同用户名/Home，路径包含空格和非 ASCII 字符；
3. 没有作者机器的 sibling repo、缓存和虚拟环境；
4. 声明支持的 OS/架构；未实测平台不得写“支持”；
5. 必需插件不存在、版本过低、鉴权缺失和离线；
6. 相同 lock/digest 是否得到相同 Schema、入口和确定性基线；
7. Runtime 生成物是否只写到声明 Root；
8. Source archive 与容器/二进制 Artifact 的 SBOM 和 Provenance 是否可回读。

Dev Container 能统一大量开发依赖，OCI Digest 能固定镜像身份，SLSA/in-toto 能描述来源与步骤；但 Host bind mount、CPU/OS 差异、外部服务、插件权限和 Secret 仍需单独测试。故“有容器”只能算环境基线，不能直接算跨设备 PASS。

### 31.4 MCP、A2A 与协议边界

MCP/A2A 可用于声明工具 Schema、资源 URI、任务状态和 Artifact 交接，但协议连接不自动提供工具可信、权限最小化或审计独立性。MCP 工具注解必须视为不可信，除非来自受信 Server；2026 年 MCP Release Candidate 已将旧 Roots 机制替换为工具参数、Resource URI 和 Server Configuration，更支持本方案的逻辑资源绑定，也意味着不能再把 Roots 当权限边界。

## 32. 是否继续增加其他“工程”

### 32.1 三个现有工程覆盖了什么

当前三工程可理解为三个主要控制域：

| 控制域 | 主要责任 | 不能替代 |
|---|---|---|
| Main / 执行工程 | 生产实现和运行证据 | 不能自我签发独立语义 PASS |
| External Lab / 校验工程 | 从原始 Artifact 重算和对抗验证 | 不能替代权限、发布或身份连续性决策 |
| Linkage / 联通工程 | 校验版本、接口、Hash 和交接连续性 | 不能证明业务语义正确 |

最新 Harness 工程研究常把完整系统分成 Execution、Tooling、Context、Lifecycle/Orchestration、Observability、Verification 和 Governance 等能力层。对照后，v2.9 还缺四个横切控制面：

1. `POLICY_GOVERNANCE`：Charter Compiler、PDP/PEP、Policy Receipt；
2. `DURABLE_ORCHESTRATION_RECOVERY`：事件日志、调度、幂等、Checkpoint/Resume、Budget；
3. `OBSERVABILITY_REPLAY_LEDGER`：原始事件、Trace、Artifact Index、重放和 Reconciler；
4. `PORTABILITY_SUPPLY_CHAIN`：环境/工具/插件合同、SBOM、Provenance 和 clean-clone 验证。

Expert Intent/Context Engineering 也是一项能力，但默认应属于 Factory 的上游编译面；只有高风险组织才需要拆成独立需求评审工程。

### 32.2 不建议固定扩成七个仓库

更多工程会增加接口、版本、授权和等待成本。研究也表明，多 Agent 收益会随基础模型能力和协调开销变化，规模更大不保证更可靠。因此 v2.9 使用：

```text
Capability Plane
→ Risk / Assurance Profile
→ Project Topology Profile
→ concrete repos, processes and identities
```

- 低/中风险：3 个权威工程 + 4 个横切模块/服务；
- 高风险：Policy、Lab、Linkage/Provenance 可拆成独立 repo/process/identity/signer；
- 极高风险：再引入外部组织、异构 Validator/Provider 或人工批准机构。

结论：**可以增加能力工程，但不应把工程数量写死。**稳定性来自职责、信息流、权限和证据的可验证分离，而不是目录数量。

## 33. 三个 CLI、同一任务和独立性

### 33.1 明确回答

“执行包—校验工程—联通测试”在设计上是三个不同责任域，其中 Lab 和 Linkage 应有各自 CLI/入口，Main 也有自己的执行入口；但这不自动意味着三个独立 Codex CLI，更不意味着认证级独立。

如果一个父 Chat 同时发起三个 Codex CLI/子 Agent，它们通常仍会共享部分系统性因素：上游 Prompt 和错误假设、父任务选择性摘要、同一工作目录或配置、同一凭据和网络、同一模型家族、同一工具实现，以及由父 Agent 决定采信哪个结果。它适合协调和并行调查，不适合仅凭“启动了三个进程”就声称独立认证。

### 33.2 独立性等级

| 等级 | 条件 | 可声称的能力 |
|---|---|---|
| `L0_NOMINAL` | 仅名称/Prompt 角色不同 | 角色模拟，不是独立验证 |
| `L1_PROCESS` | 独立进程，但共享 Chat/workspace/凭据/实现 | 故障隔离有限，可做并行检查 |
| `L2_CONTEXT_WORKSPACE` | 独立顶层任务、worktree/container、状态库与只读 Artifact Handoff | 防上下文污染和写冲突，但仍可能模型/实现同源 |
| `L3_AUTHORITY` | 再分离权限、Credential、Signer、Validator 实现和发布权 | 可用于多数高风险内部认证 |
| `L4_EXTERNAL` | 外部组织/Provider/基础设施或人工审计机构 | 用于极高风险与强对抗独立性 |

每个 Program 用 `CONTROL_DOMAIN_MATRIX.json` 按维度记录真实等级，不使用一个总布尔值掩盖部分共享。

### 33.3 推荐运行方式

高风险路径建议：

1. Main、Lab、Linkage 使用独立顶层任务/会话，而不是同一聊天的隐式上下文；
2. 使用独立 worktree/container、State Root、Credential、Secret Scope 和输出目录；
3. 只通过 Hash 锁定、只读、签名的 Artifact Envelope 交接，不传递 Producer 的隐藏推理或“应该 PASS”的结论；
4. Lab 使用独立 Fixture、Oracle 和实现；能确定性重算的指标不交给第二个 LLM 猜；
5. 语义判断确实需要模型时，使用盲测、不同 Prompt/实现，必要时使用异构 Provider，并承认仍有相关错误残余；
6. Linkage 只确认身份/接口/版本，不继承或提升 Lab 的语义 Claim；
7. 父 Orchestrator 可以排程、等结果、汇总状态，但不能修改 Lab Result、代签或成为三个域的共同授权者；
8. 最终 Certificate 要记录每个控制域的独立性等级和剩余共同失效风险。

OpenAI Codex 的官方实践同样建议：独立结果使用单独 Chat，平行编码使用独立 worktree；Subagent 会增加 token 消耗且主线程仍收集其摘要。`codex exec --json`、独立 sandbox 和必需 MCP 的 fail-closed 设置适合做可审计执行入口，但 CLI 隔离仍需配合 workspace、权限、状态和 Validator 分离。

## 34. v2.9 隔离启动决议与在途项目影响

### 34.1 本次重新 Check 的决议

| 检查项 | 结论 |
|---|---|
| 是否需要升级至 v2.9 | **需要**。v2.8 的身份/流程控制保留，但无法单独关闭语义、政策执行、长任务恢复、共同失效和跨设备发布问题 |
| 是否在当前 v2.8 目录修改实现 | **不允许**。当前目录仍承担 v2.8 Factory 和在途 Program；本文只修改 Proposal |
| v2.9 如何启动 | 从已确认 v2.8 commit/spec lock 通过 allowlist 导入到新根、新 Git、新 Program/SQLite/State/Output Root |
| 是否直接继承 v2.8 PASS/Certificate/Authorization | **不允许**。仅作带 Hash 的历史 Import Evidence |
| 来源案例是否仍是平台默认 | **不是**。只保留 Target Profile/Golden Canary 身份 |
| 三工程是否必须变成三个 Codex CLI | **不是**。CLI 是入口；独立性由上下文、workspace、权限、状态、实现和签名共同决定 |
| 是否立即增加固定第四/第五工程 | **不建议**。先实现 Capability Plane 与 Topology Profile，再由 Assurance Risk 决定物理拆分 |

### 34.2 对正在进行项目的影响控制

只要遵守以下条件，文档升级和后续 v2.9 开发不会影响现有 v2.8 执行：

- v2.8 目录、SQLite、runs、锁、进程、端口、缓存、Output Root、虚拟环境和证书路径全部只读；
- v2.9 不从当前未提交工作树复制代码，不向 v2.8 写 migration marker 或兼容字段；
- 不复用 Program ID、authorization token、attempt/session ID、release pointer 或 signer key；
- 不让 v2.9 默认发现/扫描/执行 v2.8 的进行中 Workpack；
- Port/Socket/MCP Server name、container network 和环境变量前缀均显式 namespaced；
- Phase 0 前后记录 v2.8 Tree/Spec/DB/Process Snapshot 并比较；
- 任何 v2.8 修复继续走原版本规则；任何 v2.9 变更只进入新版本证书链。

本文没有执行 Workpack、启动 Driver、安装工具、迁移 SQLite、创建 v2.9 Program 或修改 v2.8 Runtime。真正启动新目录前，仍需一次明确的“创建 v2.9 隔离根与导入基线”实施授权。

### 34.3 本次只读影响快照

2026-08-01 复核时，v2.8 Factory 中至少存在四个独立状态库：

- `PROGRAM-CODEX-VIDEO-EDITOR-PLUGIN-HYBRID-V0-1`；
- `PROGRAM-CODEX-VIDEO-EDITOR-PLUGIN-HYBRID-V0-3`；
- `PROGRAM-SKILL-FORWARD-TEST`；
- `PROGRAM-VSCDSL-VIDEO-PROMPT-HARNESS`。

同一时点还观察到 `repo://codex-video-editor-plugin-execution-runtime/v0.29` 正在执行 `LINKAGE_SELF_CONFORMANCE_PASS / LINK-SELFTEST`。该执行拥有自己的 Candidate、Execution、State 和 Evidence Root，本次文档更新未进入这些 Root，也未向任何 Factory SQLite、Workpack、授权或运行证据写入。此快照只证明复核时点的在途面，后续启动 v2.9 前仍需重新读取进程和状态，不能把本段当成永久锁。

这进一步说明：不能从当前工作树直接复制并启动 v2.9，也不能复用默认发现逻辑。v2.9 Phase 0 必须先做 `ACTIVE_PROGRAM_AND_RUNTIME_CONFLICT_SCAN`，对 Program ID、Root、PID/lease、port/socket、MCP Server name、环境变量前缀和 signer key 逐项判重。

## 35. 研究与规范来源

### 35.1 多轮澄清与意图锁定

- [SAGE-Agent: Structured Uncertainty guided Clarification for LLM Agents（ACL Findings 2026）](https://aclanthology.org/2026.findings-acl.2028/)：区分规格不确定性与模型不确定性，并以信息价值和提问成本选择澄清；
- [Uncertainty Quantification in LLM Agents（ACL 2026）](https://aclanthology.org/2026.acl-long.738/)：总结 Agent 不确定性中的异构对象、交互动态和细粒度评估难题；
- [Clarify When Necessary: Resolving Ambiguity Through Interaction with LMs（NAACL Findings 2025）](https://aclanthology.org/2025.findings-naacl.306/)：用可能意图分布和提问效用判断何时澄清；
- [ConsistentChat: Building Skeleton-Guided Consistent Multi-Turn Dialogues for Large Language Models from Scratch（EMNLP 2025）](https://aclanthology.org/2025.emnlp-main.424/)：用对话骨架减少长对话意图漂移；
- [Teaching Language Models To Gather Information Proactively（EMNLP Findings 2025）](https://aclanthology.org/2025.findings-emnlp.843/)：训练模型主动提出有针对性的问题；
- [ClarifyCodeBench（2026 预印本）](https://arxiv.org/abs/2607.00711)：代码生成强不等于歧义发现强，多重歧义仍是明显短板；
- [Automated Repair of Ambiguous Natural Language Requirements（2025 预印本）](https://arxiv.org/abs/2505.07270)：分解与最小修复比直接让模型重写整段需求更可靠。

### 35.2 Agent/Harness 可靠性、共同失效与成本

- [AI Agents That Matter（TMLR 2025）](https://openreview.net/forum?id=Zy4uFzMviZ)：Agent 评估需要同时报告成本、准确性、可复现性和基线；
- [Correlated Errors in Large Language Models（ICML 2025）](https://arxiv.org/abs/2506.07962)：不同模型和 Provider 仍可能产生相关错误，不能把模型数量等同于独立证据；
- [Can Dependencies Induced by LLM-Agent Workflows Be Trusted?（NeurIPS 2025）](https://openreview.net/forum?id=rDqZjKIeda)：工作流中的条件依赖假设可能失真，需要分解和一致性检查点；
- [Single-agent or Multi-agent? Why Not Both?（2025 预印本）](https://arxiv.org/abs/2505.18286)：混合级联可在准确性和成本间优于固定单/多 Agent 选择；
- [Agent Harness Engineering: A Survey（2026 OpenReview 稿）](https://openreview.net/forum?id=eONq7FdiHa)：将 Harness 分为执行、工具、上下文、编排、观测、验证和治理等层；
- [Code as Agent Harness（2026 预印本）](https://arxiv.org/abs/2605.18747)：强调反馈、共享状态、一致性、回归和人类监督仍是 Harness 难点；
- [LLM-as-Code Agentic Programming for Agent Harness（2026 预印本）](https://arxiv.org/abs/2606.15874)：主张由确定性程序控制循环、分支和停止，只在需要推理处调用 LLM；这与 v2.9 将状态机和 Policy 留在控制面的方向一致；
- [AI Planning Framework for LLM-Based Web Agents（2026 预印本）](https://arxiv.org/abs/2603.12710)：以序列决策和轨迹质量分析不同规划架构，支持在生成Workpack前显式选择控制/规划形态；
- [A Deterministic Control Plane for LLM Coding Agents（2026 预印本）](https://arxiv.org/abs/2606.26924)：探索Hash绑定、阶段状态机、权限和配置漂移控制；开发者效果仍待验证，故仅作为控制面设计参考；
- [LongMINT（2026 预印本）](https://arxiv.org/abs/2605.18565)：长程干扰下的 Agent Memory 仍远未达到可单独承载权威状态的水平。

### 35.3 Durable Workflow、策略与恢复

- [Temporal Durable Execution](https://temporal.io/) 与 [AI Reference Architecture](https://go.temporal.io/platform-hub/ai-engineering/ai-reference-architecture)：事件历史、Activity retry、Signal/Update、heartbeat、长任务续跑和 HITL 的成熟工程参考；
- [Temporal 社区：长工作流中的授权/执行漂移讨论](https://community.temporal.io/t/dealing-with-authorization-execution-drift-toctou-in-long-running-workflows-recommended-patterns/19610)：作为 2026 年实际落地问题信号，不作为规范性结论；
- [Temporal 社区：Durable Multi-Agent + HITL 模式分享](https://community.temporal.io/t/pattern-sharing-durable-multi-agent-ai-workflows-with-hitl-via-crewai/19715)：作为社区实现样本，需按本方案独立复核；
- [Open Policy Agent 官方文档](https://www.openpolicyagent.org/docs) 与 [部署/Decision Log](https://www.openpolicyagent.org/docs/deploy)：Policy Decision Point、Enforcement Point 和审计日志参考；
- [Autoformalization of Agent Instructions into Policy-as-Code（2026 预印本）](https://arxiv.org/abs/2606.26649)：说明自然语言转策略正在快速发展，但输出仍需测试和批准；
- [Policy-Invisible Violations in LLM Agents（2026 预印本）](https://arxiv.org/abs/2604.12177)：策略执行需要能看到相关世界状态，而非只读文字规则。

### 35.4 可移植性、供应链与互操作

- [Development Containers Specification](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainer-reference.md) 与 [OCI Image Specification](https://github.com/opencontainers/image-spec)：可复现开发环境和镜像身份基线；
- [SLSA v1.2](https://slsa.dev/spec/v1.2/) 与 [in-toto](https://in-toto.readthedocs.io/en/stable/)：来源、构建步骤和供应链证明；
- [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) 与 [2026 Release Candidate 说明](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)：工具 Schema、任务/扩展、授权强化及 Roots 迁移方向；
- [A2A Protocol Specification](https://a2aproject.github.io/A2A/latest/specification/)：跨 Agent Task 状态、消息和 Artifact 交接参考；
- [OpenAI Codex：Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)、[Projects/Chats](https://learn.chatgpt.com/docs/projects)、[Long-running work](https://learn.chatgpt.com/docs/long-running-work)、[Hooks](https://learn.chatgpt.com/docs/hooks) 与 [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)：任务/上下文隔离、worktree、生命周期执行点、token 成本和可审计 CLI 入口的官方实践。

## 36. 从校验优先修正为生产架构优先

### 36.1 为什么模型遇到问题常先增加校验

这是一个真实的系统偏置，不应解释为“模型更谨慎”后就结束。常见原因有五类：

1. **结果比生产推理更容易观察**：模型能直接看到错误文件或失败样本，却不一定看得到Producer内部如何分解任务、选择Rule和决定停止；
2. **添加Validator改动较小**：新增一个检查器通常比重构控制流、状态和模块边界更局部，模型会自然选择低修改量方案；
3. **治理任务的权限偏向只读**：在Authoring/Review阶段，检查是安全且被允许的，生产路径修改可能需要新的授权；久而久之提案也容易围绕检查展开；
4. **基准奖励偏向可判定PASS**：测试、Schema和Judge能提供立即反馈，而“架构是否更合理”难以单次量化；
5. **当前案例的入口就是假阳性**：来源案例首先表现为弱Validator允许模板轮转通过，导致根因分析从Oracle倒推，未充分前推到“Producer为什么会生成模板”。

这会形成`VERIFICATION_SUBSTITUTION`：把“能发现错误”错误替代为“能更少地产生错误”。两者都需要，但不是同一能力。

### 36.2 v2.9的修复顺序

每个Finding先标注根因平面，并按以下顺序处理：

```text
1. INTENT
2. ARCHITECTURE
3. DOMAIN_RULE / TARGET_CAPABILITY
4. PLANNER_CONTROLLER
5. EXECUTOR / MODULE
6. GOVERNANCE_POLICY_ENFORCEMENT
7. VALIDATOR_ORACLE
8. CERTIFICATION
```

例：批量结果只改变编号和少量表面字段，核心内容仍然模板化。

- 若需求没有定义“集合级差异”的可观察含义，修Intent；
- 若架构只有一个模板循环，没有概念探索/选择结构，修Architecture；
- 若Rule没有规定场景、机制、叙事、视听和角色关系的差异维度，修Domain Rule；
- 若Controller允许一次结果复制扩展，修Run Contract；
- 若Executor忽略主题和知识，修Producer Module；
- 上述修完后，再让Oracle拒绝残余模板化。

只有第7层有问题时，才以Validator为主要修复。前六层未改而只加检查器，Finding状态只能是`DETECTION_IMPROVED_PRODUCTION_ROOT_CAUSE_OPEN`。

### 36.3 强锁生产环节，不是强锁模型的每个字

生产强锁应锁定确定性骨架，把需要创造力的部分留成受控槽位：

```text
Controller owns:
  stage order
  branch conditions
  loop budget
  allowed tools
  state transitions
  retry / stop / return path

LLM owns only:
  bounded semantic interpretation
  candidate generation
  comparison/explanation within schema
```

例如Controller规定：必须读取Input Facts和Applicable Rules，产生Profile声明数量的候选，逐项调用Target Compiler，达到预算后停止；LLM只能为某个候选填入Schema约束内容，不得改变数量、跳过Rule Binding、增加未授权工具或把失败写成PASS。

2026年的[LLM-as-Code Agentic Programming](https://arxiv.org/abs/2606.15874)同样把循环、分支和停止交给确定性程序，只在需要推理处调用模型。该工作仍是预印本，但其控制面方向与本方案一致。相关Harness综述也指出，仅靠Context Engineering不能关闭长期执行漂移，[Lifecycle/Orchestration必须同时管理控制流和操作状态](https://openreview.net/forum?id=eONq7FdiHa)。

## 37. Requirement Freeze后的Harness架构设计层

### 37.1 新的两次锁定

v2.9不应从Requirement Freeze直接跳到Workpack生成，而应增加Architecture Design Epoch：

```text
REQUIREMENT_READBACK
→ REQUIREMENT_FREEZE
→ CAPABILITY_DECOMPOSITION
→ ARCHITECTURE_PROPOSAL
→ ARCHITECTURE_CLARIFICATION
→ ARCHITECTURE_READBACK
→ ARCHITECTURE_LOCK
→ WORKPACK / RUN CONTRACT COMPILATION
```

Requirement Lock回答“必须实现什么”；Architecture Lock回答“准备怎样实现”。Architecture问题若暴露了新的用户语义或改变Scope，必须返回Requirement `REOPEN`；若只是冻结范围内的实现选择，则只更新Architecture Epoch。

### 37.2 设计引导需要补全什么

Factory不必独立发明完整架构，但必须根据输入提出候选并暴露缺口，至少引导以下问题：

1. **Capability**：系统必须具备哪些生产能力，而非哪些检查器？
2. **Behavior/State**：输入到输出经历哪些状态，谁持有权威状态？
3. **Decision Point**：哪些决定可用确定性Rule，哪些必须语义推理，哪些必须人工？
4. **Data/Context Flow**：每一步能看到什么，禁止看到什么，结果如何传递？
5. **Stage/Subharness/Module**：每项能力应以哪种结构落地？
6. **Rule/Policy**：业务规则、权限规则、经验策略和Target限制分别是什么？
7. **Failure/Recovery**：局部失败回到哪里，是否幂等，如何取消和恢复？
8. **Budget/Latency**：哪些步骤并行，哪些使用高成本模型，停止条件是什么？
9. **Observability**：生产决策需要记录哪些Decision Trace，而不仅是最终PASS？

系统应输出1–3个Architecture Candidate，列出假设、优缺点、成本、漂移面和需要用户决定的问题；不应直接把第一个候选冻结为唯一设计。

### 37.3 Stage、Subharness、Module和Semantic Slot的选择

| 结构 | 中文 | 适用条件 | 不适用条件 |
|---|---|---|---|
| `STAGE` | 阶段 | 同一Controller中的有序生命周期步骤，共享Program State，完成后进入明确下一状态 | 不适合拥有长期局部记忆、独立循环或不同权限的复杂子系统 |
| `SUBHARNESS` | 子Harness | 有独立目标、局部状态、上下文、工具集、预算、重试/停止和产物，可被父Controller调用 | 不应只为调用一次模型或包装一个函数而创建 |
| `MODULE` | 模块 | 输入输出明确、无自主控制流、可重复调用，优先确定性实现 | 不适合自行决定下一Stage、无限循环或扩权 |
| `SEMANTIC_DECISION_SLOT` | 语义决策槽 | 只有确实需要语言/视觉理解或创意生成时调用LLM，输入输出有Schema和预算 | 不得拥有全局状态、工具发现、发布权或自由改变拓扑 |

选择规则：

```text
有独立局部目标 + 状态 + 循环/恢复 + 专属工具？
  yes → SUBHARNESS
  no

只是生命周期先后顺序？
  yes → STAGE
  no

可由确定性输入输出函数完成？
  yes → MODULE
  no

需要语义判断但不应拥有控制流？
  yes → SEMANTIC_DECISION_SLOT
```

Subharness数量不是智能程度指标。拆分只有在上下文隔离、局部重试、工具/权限差异、并行或职责复用带来明确收益时才成立。

### 37.4 Rule、Policy、Heuristic、Capability和Oracle不是同一种规则

| 类型 | 回答的问题 | 示例 |
|---|---|---|
| `DOMAIN_RULE` | 业务产出必须怎样形成 | 输入实体标识不得在输出中互换 |
| `GOVERNANCE_POLICY` | 谁在什么条件下允许做什么 | 未授权不得联网或安装真实目标 |
| `HEURISTIC` | 通常怎样做效果更好 | 信息不足时先提出多个受边界约束的候选假设 |
| `TARGET_CAPABILITY_CONSTRAINT` | 工具/模型客观能做什么 | 某Target只接受特定输入格式或上下文长度 |
| `ORACLE_RULE` | 如何判断结果满足要求 | 从原始输出重新计算Profile声明的关键指标 |

用户所说的`politic`在工程上建议统一写作`Policy`。很多案例中的“隐性Policy”实际混合了Domain Rule、Heuristic、Target Capability和Governance Policy；如果不拆开，就会把效果建议错误做成硬门，或把安全边界错误当成可选建议。

### 37.5 Architecture到Run的最小合同

每个Stage/Subharness/Module至少声明：

- `purpose`与Requirement/Capability来源；
- Typed Input/Output；
- State Owner和可读/可写状态；
- Allowed Tools与Capability Binding；
- Applicable Domain Rules、Governance Policies和Heuristics；
- 是否含Semantic Decision Slot及其模型能力/Schema/预算；
- Preconditions、Success、Failure、Retry、Cancel、Timeout和Return Path；
- Decision Trace与Produced Artifact；
- 禁止的Proxy、Fallback和越权动作。

这样Start Package编译的不是“若干检查任务”，而是可解释的生产拓扑和运行合同；Evidence Obligation随后绑定这条生产路径。

## 38. 同一Codex Chat中的隔离与真正独立

### 38.1 不能完全解决的事实

在同一个父Chat中，父Agent选择任务、准备输入、启动CLI、接收摘要并决定下一步，因此仍存在共同上游和共同采信者。即使启动三个`codex exec`、更换Prompt或模型，也不能诚实声称完全独立。

正确目标分两级：

- **同Chat**：减少上下文污染、代码写冲突和直接自我确认，声明`COORDINATED_SEPARATION`；
- **认证级**：使用不继承父Chat上下文、独立身份/Signer/发布权的顶层任务、CI Job或外部Lab，声明`INDEPENDENT_CERTIFICATION`。

### 38.2 同Chat可实施的最强隔离协议

1. 父Chat只做Coordinator，不写Lab结论、不改Validator输出、不持有最终Signer；
2. 每个CLI使用独立Thread/Session、worktree/container、State Root、Output Root和最小Credential；
3. 输入使用不可变`BLIND_TASK_ENVELOPE`，只包含Requirement、原始Artifact、允许工具和输出Schema，不包含Producer的结论、隐藏推理或“期望PASS”；
4. Main、Lab、Linkage使用不同Prompt模板和Fixture；Lab关键判定使用独立实现，能确定性计算的部分不用第二个LLM；
5. 每个结果由运行身份签名，并包含Input/Tool/Model/Code Hash；
6. 结果进入只读Inbox，父Chat不能覆盖，只能追加Coordinator Event；
7. 聚合器使用确定性`ALL_OF / QUORUM / DISAGREEMENT_STOP`合同，不能由父模型临时选择自己喜欢的结果；
8. 发生分歧时保存全部原始结果并升级到外部控制域，不让同一Chat继续“讨论到一致”；
9. Certificate明确写`common_context_residual_risk`和独立性等级。

该协议能明显减少直接污染，但不能消除模型相关错误。2025年的[Correlated Errors in Large Language Models](https://arxiv.org/abs/2506.07962)发现，即使跨架构和Provider，较强模型的错误仍可能高度相关。因此优先级应是：确定性Rule/Oracle > 不同实现 > 盲化和权限隔离 > 异构模型；不是简单增加Agent数量。

### 38.3 认证级独立的升级路径

```text
L0  同一Prompt中的角色扮演
L1  同Chat独立CLI/process
L2  同Chat盲化任务 + 独立workspace/state/permission
L3  独立顶层任务/CI identity/signer + 不可变交接
L4  外部组织或独立Provider/基础设施
```

v2.9 Authoring/研发可使用L2提高效率；High风险内部Certification至少L3；极高风险、外部合规或强对抗项目再采用L4。

## 39. 非规范案例与Target Profile交接

Target-specific的Requirement、领域Rule、Heuristic、Capability、Executor、Topology、Fixture、Oracle和候选生产架构必须保存在Profile/Case层，不进入Core正文。

交接顺序是：

```text
Case Observation
→ Finding Classification
→ Rule / Policy / Heuristic / Capability / Oracle拆分
→ Target Profile Candidate
→ Expert Review与必要澄清
→ Target Profile Freeze
→ 绑定Frozen Core Extension Point
→ Runtime Decision Trace
```

Rule Candidate Mining属于归纳：案例只能提出候选。Runtime消费冻结Rule属于演绎：只能执行已经确认并绑定Profile的规则。模型不得在一次运行中把新发现的案例模式静默升级为Hard Rule、平台Gate或新Subharness。

Core仍需提供“设计补全”能力：发现缺失Capability、State、Decision Point和Failure Path；提出1–3个架构候选；解释Stage/Subharness/Module/Semantic Slot选择；暴露Rule冲突和未确认能力。但所有建议必须先写入Architecture Decision，不得因为某个案例看起来特殊就直接改变控制流。

## 40. 案例去偏置与链路收敛

### 40.1 R7已完成的文档修复

R6同时承担回溯报告、平台规范、Profile示例和案例测试，容易让首个案例锚定升级方向。R7不再只声明“案例非规范”，而是完成物理拆分：

| 文档层 | 内容 | 权威性 |
|---|---|---|
| 当前主文档 | Domain-neutral Core升级合同、迁移与验收 | `PROPOSAL-R7` |
| `SOURCE_CASE_001` | 来源案例Requirement、Finding、证据、Fixture与候选拓扑 | `NON_NORMATIVE_SOURCE_CASE` |
| R6历史快照 | 拆分前完整原文 | `HISTORICAL_NON_NORMATIVE_ARCHIVE` |

主文档不再保存Target产品名、专属字段、固定候选数、领域语法、Target-specific Oracle阈值或案例生产拓扑。

### 40.2 唯一依赖方向

```text
Case
→ Target Profile
→ Frozen Core Extension Point
```

Core不得读取Case；加载Profile不得修改Core状态机、Gate、CLI、Stage类型、重试和停止语义；Fixture失败不得直接增加平台分支。

### 40.3 Case-to-Core Promotion

每个案例Finding先归类：

| 分类 | 修改位置 |
|---|---|
| `PLATFORM_INVARIANT_DEFECT` | 满足晋升条件后修改Core |
| `PROFILE_VARIATION` | 只修改Target Profile |
| `IMPLEMENTATION_DEFECT` | 修Producer/Controller/Module |
| `FIXTURE_OR_ORACLE_DEFECT` | 修Fixture/Oracle |
| `NO_CHANGE_REQUIRED` | 记录并停止 |

单一案例只能形成Candidate Finding。平台晋升必须满足以下任一条件：

- 领域无关不变量可以形式化说明；
- 同一缺陷在至少两个非来源、彼此不同的Profile中独立复现；
- 必须立即封闭的安全/权限边界获得显式Architecture Review批准。

### 40.4 控制流净增约束

Architecture变更顺序必须是：

```text
参数化现有节点
→ 替换或收缩错误节点
→ 复用Frozen Extension Point
→ 最后才考虑净新增控制节点
```

`CONTROL_FLOW_DELTA.json`逐项记录新增、替换和删除的状态、分支、Stage、Subharness、人工门、重试、回退、Oracle与外部依赖。净新增必须解释现有节点为何不能承载、新责任归谁、旧路径为何删除或保留，以及对成本、恢复、可移植性和共同失效面的影响。解释不完整时返回`ARCHITECTURE_CHANGE_NOT_JUSTIFIED`。

### 40.5 消融与替换验收

R7要求：

1. `Case Ablation`：不挂载任何Case/Profile目录时，Core仍可编译、解释和测试；
2. `Case Hash Stability`：移除来源案例后，Core Schema、Gate、状态机、CLI、Extension Point和通用路由的规范化Hash不变；
3. `Case Substitution`：换入不同领域Profile，只允许Profile数据、Rule、工具与Oracle改变；
4. `No Reverse Import`：静态依赖图不存在Core → Profile/Case边；
5. `No Fixture Routing`：Fixture内容和期望Finding不参与生产路由。

### 40.6 当前边界

R7完成的是文档结构与设计合同修复，不是实现证明。只有在独立v2.9新根中真正完成物理目录、编译依赖扫描、Case Ablation、Case Substitution和Control Flow Delta测试，才能声称平台摆脱来源案例偏置。

