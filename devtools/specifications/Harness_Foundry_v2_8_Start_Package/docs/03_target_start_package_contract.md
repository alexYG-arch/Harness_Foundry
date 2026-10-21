# 目标初始宪章 Start Execution Package 契约

## 1. 契约目的

本文规定模型使用 2.8 后应生成什么，以及在何处停止。目标 Start Execution Package 是后续工程 coding 与受控自动推进的起点，必须足以让新的会话在不依赖原聊天记忆的情况下理解：

- 为什么建；
- 建什么与不建什么；
- 谁拥有哪类事实和动作；
- 先做什么、什么条件下才能继续；
- 一次可写哪些路径；
- 如何验证、回流与失效；
- 何时仍不能声明 Harness 可运行。

## 2. 目标包默认目录

推荐结构：

~~~text
<target-start-package>/
├── README.md
├── START_HERE.md
├── START.md
├── PACKAGE_MANIFEST.json
├── PROGRAM_CHARTER.md
├── TARGET_PROFILE.md
├── PROFILE_LOCK.json
├── CHARTER_LOCK.json
├── START_CONTEXT.json
├── PACKAGE_ROLES.json
├── AUTHORITY_AND_EXECUTION_BOUNDARY.md
├── PROGRAM_STATE.json
├── PHASE_DEPENDENCY_MANIFEST.json
├── PHASE_TRANSITION_LEDGER.jsonl
├── THREE_PROJECT_PROGRAM_MANIFEST.json
├── ENGINEERING_PROJECT_DAG.json
├── RELEASE_PIPELINE_MANIFEST.json
├── PROGRAM_DRIVER_CONTRACT.json
├── PROGRAM_DRIVER_STATE.json
├── PROGRAM_AUTOMATION_POLICY.json
├── AUTHORIZATION_POLICY.json
├── LOOP_POLICY.json
├── LOOP_STATE.json
├── INVALIDATION_DAG.json
├── REENTRY_PLAN.json
├── USER_ADJUSTMENT_RECORD.json
├── AUTHORING_HANDOFF.md
├── canonical_sources/
│   ├── SOURCE_MANIFEST.json
│   ├── NORMATIVE_ATOM_CATALOG.json
│   └── ATOM_COVERAGE_MATRIX.json
├── planning/
│   ├── ROADMAP.md
│   └── WORKPACK_INDEX.json
├── contracts/
│   ├── ARTIFACT_AND_INTERFACE_CONTRACTS.md
│   └── VALIDATION_AND_REVIEW_PLAN.md
├── constitution/
├── phases/
├── workpacks/
├── commands/
├── capsules/
├── schemas/
├── build_program/conformance/
├── conformance_pack/
├── linkage/
├── installation/
├── project_start_packages/        # main_build / external_lab / linkage_review
└── validation/START_PACKAGE_VALIDATION_REPORT.json
~~~

用户可调整路径或拆分方式，但 START_CONTEXT 的直接引用与 PACKAGE_ROLES 必须为以下规范角色提供唯一实际路径。

## 3. 必需语义角色

### 3.1 入口

**README**

- 说明目标包用途、状态和非能力；
- 明确它不是最终 Agent/Harness、安装包或认证结果；
- 指向 START_HERE。

**START_HERE / START**

- 定义最小读取顺序；
- 显示当前状态、开放问题和第一个合法后续动作；
- 明确 generated commands are data；
- 不包含自动启动逻辑。

### 3.2 宪章与目标

**PROGRAM_CHARTER**

必须包含 Mission、Program Outcome、Scope、Non-goals、Authority、Role、Phase、Gate、Evidence、Change、Return Path 和 Completion Claim。

**TARGET_PROFILE / PROFILE LOCK CANDIDATE**

必须描述目标类型、Runtime、Stage、工具、数据、风险、构建、安装和外部依赖。

### 3.3 上下文与调整记录

**START_CONTEXT**

必须是机器可读 JSON，至少包含：

- 包与目标：schema_version、package_id、package_version、target_id、target_type、target_root；
- 来源与映射：canonical_source_manifest_ref、package_roles_ref、authority_refs、approved_adjustment_refs；
- 控制状态：execution_mode、current_state、active_workpack、next_eligible_transition、unresolved_blockers；
- 安全默认值：execution_started、install_started、certification_started、auto_start_generated_workpacks；
- 审计字段：created_at、authoring_readback_ref。

Authoring 交付时必须满足：

~~~text
execution_mode = AUTHORING_ONLY
current_state = START_PACKAGE_DRAFT_AUTHORING_CANDIDATE | START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
execution_started = false
install_started = false
certification_started = false
auto_start_generated_workpacks = false
active_workpack = null
~~~

**USER_ADJUSTMENT_RECORD**

记录用户调整、assumption、偏离、冲突处理和批准引用。

**UNRESOLVED_HUMAN_DECISIONS**

START_CONTEXT 中每项未决决定包含 owner、影响范围、最晚解决 Gate、阻断状态和允许的临时 assumption；可拆为独立文档。没有开放问题时明确 NONE。

### 3.4 权威与执行边界

**AUTHORITY_AND_EXECUTION_BOUNDARY**

必须定义：

- 权威顺序；
- source/candidate/canonical 所有权；
- authoring 与 execution 边界；
- 允许写路径和 side-effect boundary；
- Command Manifest 的唯一执行授权；
- Build Program registration、coding、package build、isolated install、real install 和 certification 的独立授权要求；
- final Harness entrypoint 不得解析到执行包 driver。

### 3.5 意图与覆盖

**CANONICAL_INTENT**

保留经整理但未压缩语义的目标、非目标、细节、状态、异常和限制。

**NORMATIVE_ATOM_CATALOG / INTENT_ATOMS**

每个 Atom 至少包含：

- atom_id、source_ref、原始或忠实重述；
- modality、condition、owner、status；
- target_artifact_refs、verification_mode。

**ATOM_COVERAGE_MATRIX**

必须将每个 Atom 映射到 Charter、Phase、Contract、Workpack、验证和证据。不能只证明“已进入 catalog”。

### 3.6 阶段与状态

**PHASE_DEPENDENCY_MANIFEST**

必须为每个阶段定义：

- phase_id、predecessor_phase、required_predecessor_lock、entry_criteria；
- gate、output_lock、N/A lock 规则；
- invalidates_on、allowed_next_phases。

禁止存在未声明的跨阶段边。

**PROGRAM_STATE**

初始状态至少包含：

- highest_touched_phase、highest_locally_closed_phase、current_phase、next_eligible_phase；
- valid_locks、invalidated_locks、transition_ledger_ref；
- active_workpack、blockers。

Authoring 结束时不得把尚未执行的阶段标成 touched 或 closed。

**PHASE PLANS / ROADMAP**

解释各阶段目标和交付顺序。Roadmap 不得替代机器可读的 Phase Transitions。

### 3.7 Contract 与验证

**ARTIFACT_AND_INTERFACE_CONTRACTS**

为关键输入、输出、错误、receipt、entrypoint 和外部接口定义 owner、schema、版本和兼容性。

**VALIDATION_AND_REVIEW_PLAN**

必须区分：

- authoring structural check；
- coding validation；
- real Runtime verification；
- Linkage Review；
- external Conformance；
- Human Review。

每条 MUST 都要有 machine、human 或 hybrid 模式，并至少指定一个负向防假通过场景。

### 3.8 Workpack 与 Capsule

**WORKPACK_INDEX**

必须列出 Workpack ID、Phase、状态、依赖、目标、允许路径和 Capsule。

至少生成一个“下一步可候选”的初始 Workpack，但保持未执行状态。

**INITIAL WORKPACK**

至少包含：

- objective、non-goals、predecessor Lock、required inputs；
- allowed/forbidden write paths、expected outputs；
- review_mode、execution_mode、Command IDs 和声明式 Command Manifest 引用；
- validation、readback、cleanup、done definition、blocker 和 return conditions；
- capability claims explicitly not proven。

**CAPSULE**

只携带该 Workpack 所需最小上下文、Hash、路径和约束。不得依赖“见此前聊天”。

### 3.9 Handoff

**AUTHORING_HANDOFF**

必须列出：

- 产物清单、readback、Intent 覆盖与缺口；
- decisions、assumptions、blockers 和当前允许的状态声明；
- 后续第一个合法动作及所需新模式、授权和目标环境；
- 明确的 AUTHORING_STOP。

### 3.10 受控自动推进控制面

目标包还必须生成以下机器角色，具体字段见[受控自动推进](13_controlled_auto_progression.md)：

- `THREE_PROJECT_PROGRAM_MANIFEST` 与 `ENGINEERING_PROJECT_DAG`；
- `RELEASE_PIPELINE_MANIFEST`；
- `PROGRAM_DRIVER_CONTRACT` 与 `PROGRAM_DRIVER_STATE`；
- `PROGRAM_AUTOMATION_POLICY`、`AUTHORIZATION_POLICY` 与授权实例；
- `WORKPACK_RESULT`、Promotion/Revocation Ledger；
- `LOOP_POLICY`、`LOOP_STATE`、Finding Schema、Repair Routing；
- `INVALIDATION_DAG` 与 `REENTRY_PLAN`；
- Main Build、External Lab、Read-only Linkage 三个独立 Project Start Package。

这些资产在 Authoring 结束时均为未执行状态。它们必须足以让 Driver 在批准后机械得到零个或一个 next action；零个表示等待或阻断，多个表示 `AMBIGUOUS_NEXT_ACTION`，不得由模型猜测。

## 4. 文件合并与替换

为小型 Agent 合并文件是允许的，但必须同时满足：

1. START_CONTEXT 与 PACKAGE_ROLES 仍能唯一定位每个必需语义角色；
2. 不同权威层的正文没有混成第二事实源；
3. JSON 状态仍保持机器可读；
4. Intent、Phase、Workpack 和 Handoff 信息没有丢失；
5. 合并决定记录在 AUTHORING_DECISIONS；
6. 入口加载量仍受控。

不能把所有内容重新合并成单个巨型 Markdown。

## 5. 初始 Workpack 的边界

默认首个可候选 Workpack 应建立 G0 或等效建设控制基础，而不是直接实现最终业务功能。

它可以规划：

- schema、ID、Hash 与路径安全；
- candidate/canonical 隔离；
- state、ledger、promotion 和 invalidation；
- Workpack/Capsule/Command Manifest 解析；
- authoring 产物的结构化验证。

它不得在 authoring 会话中：

- 被执行；
- 自动创建最终工程代码；
- 跳到后续 Phase；
- 构建或安装 Harness；
- 调用真实 Runtime；
- 签发 Conformance 结论。

## 6. Authoring 验收

目标包可标记 START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW 的最低条件：

- 所有必需语义角色存在且 START_CONTEXT / PACKAGE_ROLES 引用可解析；
- Markdown 相对链接和 JSON 语法检查通过；
- Program Charter 与 Target Profile 不冲突；
- Intent Atom 有来源且 coverage 无静默遗漏；
- Phase Graph 无未授权跳边；
- 初始 Workpack 有前驱、边界、验证和 return path；
- 所有 generated command 均为 declarative；
- execution/install/certification 状态均为 false；
- Open Questions 的阻断面明确；
- Handoff 已重新读取实际产物。
- 三工程、Driver、Release Pipeline、授权、loop、失效和重入资产通过机器结构检查；
- 自动化负向测试已规划，且 Real Target Install 不在任何普通执行授权内。

该状态只证明目标包可供用户审阅，不证明工程或 Harness 质量。

## 7. 强制停点

完成第 6 节后必须：

1. 输出创建和检查摘要；
2. 标记 AUTHORING_STOP；
3. 不注册 Build Program；
4. 不启动首个 Workpack；
5. 不运行目标代码；
6. 不构建、不安装、不认证。

后续动作需要批准与授权，并按[Workpack 与执行模式](05_workpack_and_execution_modes.md)和[授权与硬停点](16_authorization_and_hard_stops.md)进入合法模式。一个有效授权可以覆盖多个连续节点，但不能覆盖未声明模式或硬停点。

## 8. 禁止的目标包形态

- 只有一份长篇协议，没有目标特定 Charter；
- 只有 Phase 名称，没有前驱 Lock；
- 只有测试命令，没有授权、错误语义和证据；
- 只有 summary，没有 Intent Atom 和原始来源；
- Workpack 内含自动执行或自启动指令；
- 把 execution package repository 当作 installed Harness；
- 把示例 receipt、mock 或 Python 生成记录当作 Runtime provenance；
- 声称已通过尚未搭建的 Lab、Linkage 或真实安装检查。
- 只有自然语言顺序，没有三工程 DAG、Release Pipeline 或 Driver State；
- 只有 retry 文案，没有最大轮次、振荡、升级和 resume 状态；
- 允许普通 Workpack 授权自动跨越真实目标安装。

## 9. 相关文档

[包用途、边界与权威](00_package_purpose_and_authority.md) · [用户调整策略](01_user_adjustment_policy.md) · [Authoring 工作流](02_authoring_workflow.md) · [Build、Release 与 Install](09_build_release_install.md) · [受控自动推进](13_controlled_auto_progression.md) · [验收与负向测试](11_acceptance_and_negative_tests.md)
