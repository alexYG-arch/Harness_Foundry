# Harness Foundry v2.9 最小可信执行闭环升级方案

2026-09-18 规划更新：下一轮工程请先读[通用 Codex Harness 修复与更新计划 v0.2](FOUNDRY_GENERIC_CODEX_HARNESS_UPDATE_PLAN_v0_2.md)。它整合用户最新确认的通用建设目标、PRD／项目说明场景、最小 Hash 与他人 Codex 接入标准，并提出对本 R8 中固定决策槽、实施冻结和 Authoring-only 完成边界的调整。本 R8 正文保留供追踪；新计划尚未实施，不修改旧 Program、锁、授权或导入来源身份。

## 0. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | `PROPOSAL` |
| 基线版本 | Harness Foundry v2.8 |
| 目标版本 | Harness Foundry v2.9 |
| 当前提案修订 | `PROPOSAL-R8_SCOPE_CORRECTED` |
| 范围修正日期 | 2026-08-03 |
| 发布定位 | 解决人工确认过多、自动推进不足、宪章执行不一致、预算STOP不可恢复、生产逻辑漂移和跨设备不可用 |
| 现行来源案例 | `HARNESS_FOUNDRY_V2_9_SOURCE_CASE_001.md`，仅作`NON_NORMATIVE_SOURCE_CASE` |
| 拆分前快照 | `HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN_R7_PRE_3_0_SPLIT_ARCHIVE.md` |
| 后续版本 | `HARNESS_FOUNDRY_V3_0_FOLLOW_ON_ARCHITECTURE_PLAN.md` |
| 非授权声明 | 本文不授权修改v2.8、执行Workpack、启动Driver、安装、发布、认证或Git操作 |

## 1. 执行结论

v2.9不再承担“完整Agent平台重构”。它只交付一个最小但完整的可信执行闭环：

```text
Expert Intent Lock
→ Requirement Freeze
→ Architecture Lock
→ Executable Charter Policy
→ Applicable Evidence Contract
→ Start Package Candidate
→ Risk-scoped Authorization
→ Automatic Advance Until Real Gate
→ Durable Checkpoint / Resume
→ Runtime and Independent Proof
→ Release Closure
```

v2.9必须直接解决六个原始问题：

1. 用户不再手工复制和核对大量Hash；
2. Factory Authoring和下游Runtime都能自动推进到真正需要人的决策点；
3. 宪章不再只依赖模型记忆，而是在工具调用和状态迁移处强制执行；
4. 预算、进程或上下文中断后可以从确定状态恢复；
5. Requirement Freeze后先补全生产架构、Rule和Run Contract，不以增加Validator代替生产修复；
6. v2.9从v2.8新根启动，不影响正在执行的v2.8项目，并可在干净clone中复现。

Requirement Type、Evidence Obligation、Independent Oracle和Runtime Proof仍保留，但只在Requirement声明适用时物化，不能扩展成所有项目都必须经历的固定重型链路。

## 2. P0升级目标

| P0 ID | 目标 | v2.9完成信号 |
|---|---|---|
| `P0-01` | 版本隔离 | 新根、新Program、新SQLite/State/Output；v2.8零写入 |
| `P0-02` | 意图与需求锁定 | 高关键冲突关闭；Requirement Readback和Freeze可追溯 |
| `P0-03` | 生产架构锁定 | Capability、Stage/Module/Subharness、Rule、工具和失败返回形成Architecture Lock |
| `P0-04` | 宪章强制执行 | 所有规范性Clause都有处置、Policy、执行点和Receipt |
| `P0-05` | 无手工Hash操作 | 用户确认可读风险挑战，不输入子Hash；机器验证完整Hash闭包 |
| `P0-06` | 自动推进 | Authoring和Runtime均可自动运行到阻塞问题、权限变化或不可逆风险 |
| `P0-07` | 可恢复STOP | 中断产生Checkpoint和Resume Capsule，不丢失已完成状态 |
| `P0-08` | 证据按需编译 | 结构、行为、语义Requirement只生成各自必要Evidence/Oracle |
| `P0-09` | 独立性诚实 | 同Chat结果不冒充独立认证；高风险Claim使用独立顶层控制域 |
| `P0-10` | 可移植生成与发行 | Candidate、Frozen IR、Source/Command Manifest和Git发行物无持久化本机路径；README、环境清单与运行时绑定方式一致 |

以上十项是v2.9 Release Critical Path。未列入P0的高级能力不得阻塞v2.9发布，统一迁入v3.0。

## 3. 范围边界

### 3.1 v2.9包含

- v2.8兼容读取与独立新根迁移；
- Expert Chat的高价值澄清和差量Readback；
- Requirement Lock与Architecture Lock；
- Domain Rule、Governance Policy、Heuristic、Target Capability和Oracle分离；
- 确定性Controller和有限Semantic Decision Slot；
- 全量规范性宪章条款的Policy处置与执行；
- 机器管理的Hash闭包和风险差量授权；
- Authoring与Runtime的`advance-until-gate`；
- Checkpoint、Resume、幂等与副作用不确定时的停机；
- 按Applicability选择Evidence、Oracle、Runtime和Adversarial义务；
- Main、Lab、Linkage责任分离与最低独立性声明；
- 干净clone、逻辑资源URI、环境/工具/插件声明。

### 3.2 v2.9不包含

以下能力不再作为v2.9 Release Gate：

- 自主生成完整系统架构或完整领域推理链；
- 复杂EVPI优化、学习型提问策略和大规模反例知识库；
- 分布式多主机事件编排、动态租约集群和跨组织调度；
- 自动从任意自然语言生成权威Policy而无需人工Freeze；
- 学习型Review Router、跨模型动态路由和全局成本优化器；
- L4外部组织/多Provider认证网络；
- 完整OCI/SBOM/SLSA/in-toto供应链平台；
- MCP/A2A多生态互操作框架；
- 跨案例自动晋升平台规则的治理系统；
- 大规模Canary Property Matrix和平台演化分析。

这些内容迁入v3.0，不得以“未来能力未完成”为理由阻止v2.9闭环。

## 4. 权威顺序与不可覆盖边界

v2.9必须显式冻结以下权威顺序：

```text
Platform Safety and System Authority
> Frozen Charter
> Frozen Requirement IR
> Approved Architecture Lock
> Target Profile
> Run Contract
> Current Task Instruction
> Model Inference or Heuristic
```

规则：

1. 低层内容不能覆盖高层内容；
2. Chat中的后续便利性建议不能扩大已冻结权限；
3. Architecture发现Requirement语义变化时必须`REOPEN_REQUIREMENT`；
4. Target Profile只能填写Core Extension Point，不能增加平台状态、Gate或权限；
5. 模型推断只能产生`ASSUMPTION`或`CANDIDATE`，不能静默升级为`USER_FACT`、Hard Rule或Authorization；
6. Charter、Requirement或Architecture Hash变化时，所有依赖的Policy、Run Contract、Authorization和未完成结果按依赖图失效。

## 5. 双锁设计：Requirement Lock与Architecture Lock

### 5.1 Requirement Lock

Requirement Lock回答“必须实现什么”，至少包含：

- Outcome与Non-goal；
- Actor、权限和责任边界；
- 正向、负向、错误、取消、超时和恢复；
- 输入、输出、数据、环境和Target Capability；
- Acceptance Observation；
- Requirement Kind和适用生命周期；
- 未决冲突、假设和来源。

Expert Chat每轮最多询问三个Blocking/High问题。能从本地证据得到的事实先自行核对；低风险默认值必须作为显式`ASSUMPTION`回读，不能静默Freeze。

### 5.2 Architecture Lock

Architecture Lock回答“在冻结需求内怎样实现”，至少包含：

- Capability与Behavior/State；
- Stage、Module、Subharness和Semantic Slot选择；
- State Owner和Data/Context Flow；
- Domain Rule、Governance Policy、Heuristic与Target Capability；
- Allowed Tool与禁止工具；
- Retry、Budget、Stop和Failure Return Path；
- Requirement → Architecture → Run的双向追踪。

选择规则：

| 类型 | 使用条件 |
|---|---|
| `STAGE` | 同一Controller下的有序生命周期步骤 |
| `MODULE` | 无自主控制流的确定性函数或服务 |
| `SUBHARNESS` | 确有独立目标、局部状态、工具、循环和失败恢复 |
| `SEMANTIC_DECISION_SLOT` | 规则无法唯一确定、但输入输出可被Schema限制的语义判断 |

默认优先级：参数化现有节点 → 替换错误节点 → 复用Extension Point → 最后才新增Stage/Subharness。架构建议必须列出理由、假设、成本和缺口，但v2.9不要求Factory独立做出完整领域架构决策。

## 6. 生产优先与确定性运行

修复顺序必须是：

```text
INTENT
→ ARCHITECTURE
→ DOMAIN RULE / TARGET CAPABILITY
→ PLANNER / CONTROLLER
→ EXECUTOR / MODULE
→ POLICY ENFORCEMENT
→ VALIDATOR / ORACLE
→ CERTIFICATION
```

当原始产出错误且根因位于前六层时，只增加Validator、Fixture或证书条件不能关闭Finding，只能标记：

```text
DETECTION_IMPROVED_PRODUCTION_ROOT_CAUSE_OPEN
```

确定性Controller持有：

- Stage转换；
- 循环和分支；
- 工具允许列表；
- 最大重试；
- 时间、调用和成本预算；
- 停止和回退；
- Checkpoint提交。

LLM只能在冻结的Semantic Decision Slot内返回Schema约束候选，不能增加Stage、工具、预算、权限或把失败改写成PASS。

## 7. Executable Charter P0合同

### 7.1 全量Clause处置

不是“关键Clause”，而是每一条规范性Charter Clause都必须有且仅有一种处置：

| 处置 | 含义 |
|---|---|
| `EXECUTABLE` | 编译为可机器判定Policy并绑定Enforcement Point |
| `HUMAN_DECISION` | 无法安全形式化，绑定明确人工决策点 |
| `NOT_APPLICABLE` | 有Requirement/Architecture依据和理由 |
| `CONFLICT` | 与其他权威来源冲突，禁止Freeze |

任何Clause未映射、重复映射、被弱化或处于`UNKNOWN`时，不能进入Requirement/Architecture Freeze。

### 7.2 Policy等价与执行

每条Clause绑定：

- Clause ID、原文Locator和原文Hash；
- Policy IR；
- 输入世界状态；
- `ALLOW / DENY / REQUIRE_HUMAN / UNKNOWN`；
- 正向、负向和冲突测试；
- Tool Gateway、State Transition Guard或Release Gate；
- Decision Receipt；
- Return Path和waiver规则。

Policy编译器必须输出`CHARTER_POLICY_COVERAGE`，证明没有遗漏规范性Clause。Policy测试不能只由同一生成逻辑自证；至少使用独立Fixture/实现复算映射和预期Decision。

### 7.3 失效与Fail-closed

- Charter Hash变化：Policy、Architecture、Run Contract和Authorization失效；
- Policy实现或测试变化：未完成Authorization失效；
- Policy依赖的世界状态缺失：`UNKNOWN`，默认停止或请求人工；
- Enforcement Point不可用：禁止绕过Policy继续执行；
- Decision Receipt缺失：该状态迁移不能Promotion。

## 8. Requirement、Evidence与Oracle的按需链

每个Atom声明正交字段：

- `requirement_kinds[]`：结构、行为、输出语义；
- `verification_obligations[]`：结构验证、真实运行、独立重算、负向或篡改；
- `lifecycle_scopes[]`；
- `criticality`。

兼容规则：

| Requirement | 最低关闭证据 |
|---|---|
| 结构/文件形状 | Schema、结构或Hash身份检查 |
| Runtime行为 | 真实Executor Receipt和原始输出 |
| 输出语义 | Target Profile提供的Independent Oracle |
| 安全/拒绝要求 | Negative/Tamper Evidence |
| 纯结构项目 | Runtime和Semantic Oracle为`NOT_APPLICABLE` |

Hash只证明身份和连续性；Linkage只证明同一对象贯穿构建、测试和安装；Producer自报不能独立关闭Requirement。

## 9. 无手工Hash的授权模型

### 9.1 人类确认什么

人类界面展示：

- 本次目标与差量；
- 允许写入、网络、Secret和外发；
- 是否触碰真实目标；
- 最大时间、调用、成本和修复次数；
- 停止门和不可逆动作；
- 与上一授权相比新增或失效的风险。

用户确认一个人类可读挑战操作。挑战在机器侧绑定：

```text
milestone_id
+ authorization_bundle_root_sha256
+ risk_delta_sha256
+ state_hash
+ expiry
```

用户不得被要求输入或逐项核对子Hash；Root Hash可以展示用于审计，但不作为主要人工输入。

### 9.2 Parent Authorization与Derived Attempt Bundle

为避免每次目标代码修复都重新找人：

1. Parent Authorization冻结允许修改的Target Root、命令类别、预算、修复轮数、权限和停止门；
2. 授权范围内产生的新Target Artifact由Runtime自动生成Derived Attempt Bundle和新子Hash；
3. Derived Bundle必须可追溯到Parent、Attempt、输入和差量，不能扩大Scope；
4. Target实现Hash变化但仍在已授权修复围栏内，不产生新人工门；
5. Driver、Policy Engine、Validator信任逻辑、权限、网络、Secret、真实目标或停止门变化，必须新的人类风险授权；
6. 未变化子项按Hash引用复用，不重复复制Evidence。

因此，机器仍精确绑定每次执行的字节，人类只在风险或控制面变化时重新决定。

## 10. Authoring自动推进

### 10.1 单一入口

v2.9新增一个组合入口：

```text
hffactory advance-authoring-until-gate --program-id PROGRAM_ID
```

它在同一State CAS和幂等合同内自动执行：

- Requirement分类；
- Clause处置与Policy Coverage；
- Capability/Architecture候选；
- Rule/Policy/Capability分层；
- Run Contract；
- Evidence Applicability；
- Readback准备。

内部检查可以产生Finding，但不得要求用户逐个调用审计CLI。

### 10.2 Authoring状态机

```text
INTAKE
→ AUTO_COMPILING
→ WAITING_USER_DECISION          # only Blocking/High ambiguity or conflict
→ READY_FOR_READBACK
→ WAITING_REQUIREMENT_FREEZE
→ START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
```

可恢复的外部问题使用`WAITING_EXTERNAL_STATE`，内部Schema、Coverage、Policy和Architecture检查只是`AUTO_COMPILING`的子状态，不得各自成为默认人工停顿。

Factory仍在`AUTHORING_STOP`结束，不批准、不执行Workpack、不安装、不认证。

## 11. Runtime自动推进与真实人工门

### 11.1 Runtime状态机

```text
PREPARING_AUTHORIZATION
→ WAITING_RISK_AUTHORIZATION
→ AUTHORIZED_RUNNING_TO_GATE
→ MILESTONE_COMPLETE
```

异常分支：

```text
AUTHORIZED_RUNNING_TO_GATE
├→ CHECKPOINT_RESUMABLE
├→ WAITING_EXTERNAL_STATE
├→ WAITING_SCOPE_CHANGE_AUTHORIZATION
└→ HARD_STOP_UNKNOWN_SIDE_EFFECT
```

### 11.2 自动执行

在Parent Authorization围栏内自动：

- 下一个DAG Node；
- 幂等命令；
- 已声明的Target局部修复；
- 暂时错误的限定重试；
- 只读复验；
- Receipt和Result收口；
- Derived Attempt Bundle；
- 无风险增量的下一里程碑准备。

### 11.3 人工决策

只有以下情况请求人工：

1. Requirement/Charter/Architecture语义变化；
2. 权限、网络、Secret、外发或真实目标扩大；
3. 控制面信任逻辑变化；
4. 安装、删除、发布等不可逆或外部影响；
5. waiver、Policy Unknown、未知副作用或无法消除的独立Validator分歧；
6. 新增预算超出已授权上限。

Repair、Release Build或Certify的名称本身不是人工门；是否需要人只由风险差量决定。

## 12. Checkpoint、Resume与预算

每个已提交节点记录：

- Program/Node/Attempt和State Hash；
- 已提交Artifact、Receipt和Event范围；
- 未执行节点；
- 禁止重复的非幂等副作用；
- Parent/Derived Authorization、有效期和剩余Scope；
- 环境、工具和Policy版本；
- 中断原因和恢复前必查项。

预算耗尽但状态唯一、无未知副作用时：

```text
CHECKPOINT_RESUMABLE
≠ BUSINESS_FAILURE
≠ NEW_AUTHORIZATION
```

恢复前重新检查授权时效、Artifact、环境、Policy和外部副作用。仅增加执行时间且仍在Parent Authorization预先允许的弹性预算内可以自动恢复；扩大预算、Scope或权限才请求人工。

## 13. 控制域与独立性最低要求

Main、External Lab和Linkage是不同责任域，不因CLI数量自动独立。

| 声明 | 最低条件 |
|---|---|
| `COORDINATED_SEPARATION` | 同Chat可用，但独立workspace/state/output、盲化输入、不可变Artifact交接 |
| `INDEPENDENT_INTERNAL_CERTIFICATION` | 独立顶层任务、凭据/Signer、Validator实现、只读交接和发布权 |
| `EXTERNAL_CERTIFICATION` | 延后到v3.0 |

同一父Chat、同一Validator复制、只换Prompt或只开新进程不能声明独立认证。父Coordinator能调度和汇总，但不能改写Lab Result或代签。

## 14. 可移植发行最低合同

### 14.1 先区分“逻辑引用”和“本机解析结果”

可移植不等于运行时永远不知道绝对路径。操作系统执行命令时最终仍需要解析出本机路径，但这个解析结果只能是当前进程的临时值，不能写回可分享制品。

```text
可分享制品中的持久字段
  repo://tools/hffactory.py
  candidate://commands/run.json
  execution://workspace/main
  source://SRC-V29-ACTIVE-PLAN
            ↓ 运行时解析器
当前设备的临时绝对路径（只存在于内存或本机非发行绑定层）
```

因此v2.9必须把路径分成两层：

| 层 | 允许内容 | 禁止内容 |
|---|---|---|
| 可分享逻辑层 | 仓库相对路径、Bundle内相对路径、受Schema约束的Resource URI、内容Hash | `/Users/...`、`C:\\Users\\...`、`file://`、`..`越界、外部symlink |
| 本机解析层 | 由CLI参数、当前仓库根、隔离运行根或声明的环境变量解析出的绝对路径 | 写回Candidate、Frozen IR、Source Manifest、Command Manifest、README或Git发行物 |

`output_root`和`execution_root`不得继续作为冻结需求里的本机绝对路径。v2.9 Requirement IR保存逻辑Root ID；本机实际Root由Program私有绑定记录解析。私有绑定属于可删除、可重建的本机状态，不得进入Candidate或发行包，也不得作为跨设备身份。

### 14.2 约束范围

以下对象都必须满足可移植规则，而不只是最终上传GitHub的源代码：

- 生成的Start Package Candidate及其`FROZEN_REQUIREMENT_IR`；
- `START_CONTEXT`、Source/Command/Executor/Environment/Toolchain/Plugin Manifest；
- Workpack、Capsule、Driver Contract和所有命令参数/工作目录引用；
- Factory源码、测试夹具、README和发布归档；
- 可交给另一设备的JSON、JSONL、Markdown和校验报告。

允许保留本机绝对路径的范围仅限本机权威SQLite/Event Store及其明确标记为`LOCAL_ONLY_NON_EXPORTABLE`的派生诊断视图；便携导出必须拒绝或剥离这些视图，绝不能把它们伪装成可分享Candidate。

### 14.3 发行与验证要求

v2.9 Git发行物和可分享Candidate必须：

- 使用仓库相对路径或逻辑Resource URI；
- 不包含本机绝对路径、越界相对引用和外部symlink；
- 不隐式依赖同级私有仓库；
- README列出安装、启动、验证、环境、工具、插件/MCP、权限和离线降级；
- 机器可读Environment/Toolchain/Plugin Manifest与README一致；
- Secret只通过声明的Runtime注入；
- 干净clone在随机路径和不同用户名下完成启动与自检。

Validator必须在生产生成器之后执行以下负向检查，但不能用校验替代生产修复：扫描POSIX/Windows用户目录、`file://`、未声明环境变量、越界`..`、外部symlink和隐式同级仓库；发现任一项均返回`LOCAL_PATH_BINDING`或更具体的失败码。Clean-clone测试还必须把Bundle复制到第二个随机根并重新解析所有逻辑引用，证明路径不是只在原目录碰巧可用。

完整SBOM、SLSA/in-toto、OCI和跨生态协议认证迁入v3.0；若项目自身安全等级要求这些能力，可由Target Profile额外声明，但不作为所有v2.9项目的固定门。

## 15. 最小制品集合

v2.9使用逻辑Bundle，而不是为每个概念增加独立人工制品：

| Bundle | 最低内容 |
|---|---|
| `REQUIREMENT_BUNDLE` | Requirement IR、Decision Ledger、Applicability |
| `ARCHITECTURE_RUN_BUNDLE` | Architecture Lock、Rule/Capability Binding、Run Contract |
| `CHARTER_POLICY_BUNDLE` | Clause Coverage、Policy IR、Tests、Enforcement Binding |
| `AUTHORIZATION_BUNDLE` | Risk Summary、Parent Authorization、Derived Bundle规则 |
| `CHECKPOINT_BUNDLE` | Event范围、Resume Capsule、副作用状态 |
| `EVIDENCE_BUNDLE` | 适用Evidence、Oracle Result和Traceability Index |
| `PORTABILITY_BUNDLE` | Root ID/Resource URI、Runtime Resolver合同、Environment、Toolchain、Plugin和Clean-clone Matrix；不包含本机绑定值 |
| `RELEASE_CLOSURE_BUNDLE` | Main/Lab/Linkage Result和允许的Claim Set |

内部文件可以分层，但：

- SQLite/Event Store是权威状态；
- JSON/JSONL是可重建读视图；
- 相同Evidence只通过Hash引用；
- 不适用Bundle或字段不物化空壳；
- 用户界面只显示结论、风险差量、阻塞原因和Return Path。

## 16. 复合Gate

v2.9只保留八个发布级Gate，细粒度Finding作为Gate内部机器检查：

| Gate | 必须证明 |
|---|---|
| `G0_VERSION_ISOLATION` | v2.8零写入；v2.9独立根与状态 |
| `G1_INTENT_REQUIREMENT_LOCK` | 高关键冲突关闭，Requirement可回读 |
| `G2_ARCHITECTURE_RUN_LOCK` | Capability有生产路径，Controller和Module边界清楚 |
| `G3_CHARTER_ENFORCEMENT` | 全量Clause处置、Policy等价、PEP与Receipt |
| `G4_APPLICABLE_EVIDENCE` | Requirement与Evidence/Oracle类型兼容，无多余链路 |
| `G5_RISK_AUTHORIZATION_UX` | 无手工子Hash，Risk Delta和Derived Bundle边界正确 |
| `G6_AUTO_PROGRESS_AND_RESUME` | Authoring/Runtime自动推进，STOP可恢复 |
| `G7_PORTABLE_INDEPENDENT_CLOSURE` | 可移植性、控制域声明和Claim Closure真实 |

Gate失败必须返回Owner、Finding、证据、禁止替代证据和最小Return Path；不得通过增加平行Gate解决同一问题。

## 17. 最小CLI面

Factory新增或收敛为：

```text
hffactory advance-authoring-until-gate --program-id PROGRAM_ID
hffactory readback --program-id PROGRAM_ID
hffactory explain-blocker --program-id PROGRAM_ID
hffactory validate-candidate --program-id PROGRAM_ID --json
```

Runtime入口：

```text
runtime prepare-risk-authorization --milestone MILESTONE_ID
runtime materialize-user-authorization --challenge-token TOKEN
runtime advance-until-gate --authorization AUTHORIZATION.json
runtime checkpoint --program-id PROGRAM_ID
runtime resume --capsule RESUME_CAPSULE.json
runtime explain-stop --program-id PROGRAM_ID
```

原有细粒度审计能力作为内部模块或`--detail`输出，不要求操作者依次运行几十个子命令。

## 18. v2.8到v2.9迁移

1. 冻结已确认v2.8 commit和Spec Lock；
2. 创建独立v2.9根、Git、Program ID、SQLite、State、Output和Execution Root；
3. 通过Import Manifest/allowlist导入规范与源代码；
4. 不导入runs、cache、lock、旧Authorization、旧Certificate、当前脏工作树和本机路径；
5. v2.8 Evidence只作Hash绑定历史输入，不自动升级为v2.9 PASS；
6. 完成Requirement和Architecture新Epoch；
7. 先实现八个P0 Gate，再加载Target Profile和来源案例；
8. 迁移期间持续验证v2.8 Tree Hash、状态库、进程、端口和输出零写入。

v2.9可以读取Legacy字段，但不静默修改v2.8 Program或原SQLite。

## 19. v2.9发布验收

v2.9只有同时满足以下条件才可发布：

1. v2.8 Spec、Program、SQLite、锁、运行进程和输出零写入；
2. P0-01至P0-10均有实现和测试证据；
3. Authoring一次组合调用可自动推进到Blocking问题、Readback或Authoring Stop；
4. Runtime在同一风险围栏内不逐Node请求人工；
5. 用户不需要复制或输入任何子Hash；
6. Target修复产生Derived Attempt Bundle但不扩大Parent Authorization；
7. 控制面、Scope、权限或不可逆风险变化必然返回人工；
8. 所有规范性Charter Clause均被处置，`unmapped_normative_clause_count=0`；
9. Clause原文、Policy、Test、Enforcement和Receipt可双向追踪；
10. Capability和Blocking/High Rule都有生产路径，Validator-only Repair不能关闭生产根因；
11. 预算/进程中断能从Checkpoint恢复，非幂等副作用不会盲目重跑；
12. Requirement只生成适用Evidence/Oracle，纯结构项目不被强制进入Runtime/语义链；
13. 同Chat结果不会被认证为独立证据，高风险内部认证满足独立顶层控制域条件；
14. 干净clone、随机路径、不同用户名和缺失可选插件测试通过；
15. 主文档、来源案例、Target Profile和Core实现不存在反向依赖；
16. Factory仍停在`START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW / AUTHORING_STOP`；
17. 未实现的v3.0能力不会被写成v2.9 PASS或阻塞v2.9发布；
18. Spec Lock、Skill Validation、测试和Git Hygiene全部通过。

## 20. 从R7迁出的能力

| R7能力 | v2.9保留部分 | v3.0承接部分 |
|---|---|---|
| Expert Chat | 最多三个高价值问题、Decision Delta | EVPI优化、学习型提问、规模化反例库 |
| Architecture Design | 缺口发现、候选解释、Architecture Lock | 自主架构综合、跨Profile拓扑优化 |
| Executable Charter | 全量Clause处置、Policy/PEP/Receipt | 高级自动形式化、多Policy推理和证明 |
| Durable Orchestration | 单Program Event/Checkpoint/Resume | 分布式租约、多主机、多任务编排 |
| Review与预算 | 确定性风险门、固定预算与恢复 | 学习型Review Router、模型级联和全局成本优化 |
| 控制域 | 同Chat降级、内部独立认证 | L4外部组织和多Provider认证网络 |
| Portability | clean clone、Manifest、无本机路径 | OCI、SBOM、SLSA、in-toto和协议认证 |
| Generality | Profile不修改Core、Case Ablation | 自动Case-to-Core Promotion与演化治理 |
| Canary | 最小互斥Profile验证Applicability | 大规模Property Matrix和跨领域基准 |
| MCP/A2A | 插件和工具声明 | 跨生态资源发现、任务互操作与能力协商 |

逐项来源和无损迁移映射见v3.0文档的`R7 Scope Migration Matrix`。

## 21. 实施顺序

```text
1. Freeze v2.8 baseline and verify zero write
2. Create isolated v2.9 root and import allowlist
3. Implement Requirement and Architecture dual lock
4. Implement complete Charter Clause disposition and enforcement
5. Implement Authoring advance-until-gate
6. Implement Parent Authorization and Derived Attempt Bundle
7. Implement Runtime advance-until-gate
8. Implement Checkpoint and Resume
9. Implement applicable Evidence/Oracle closure
10. Implement internal independent control-domain handoff
11. Run clean-clone and non-origin Target Profile tests
12. Close P0-01 through P0-10 and release v2.9
```

不得先实现v3.0高级能力再回来补v2.9自动推进、宪章闭环或授权体验。

## 22. 最终原则与非声明

```text
Human approves risk and authority, not a list of hashes.
Machines verify every bound byte and state transition.
Auto-progress stops on risk change, not on every internal check.
Every normative charter clause is disposed and enforced.
Design the producer before adding validators.
Budget exhaustion creates a resumable checkpoint, not a vague failure.
Applicability removes unnecessary runtime, oracle and evidence paths.
Same-chat coordination is useful, but it is not independent certification.
Portable means generated artifacts and clean clones can be rebound on another machine; it does not mean persisting the author's absolute paths and merely uploading them to GitHub.
v2.9 closes the minimum trustworthy loop; v3.0 scales and optimizes it.
```

本文仍是`PROPOSAL`。它不证明v2.9 Schema、Factory、Runtime、Policy、Oracle、迁移、发布或认证已经实现。
