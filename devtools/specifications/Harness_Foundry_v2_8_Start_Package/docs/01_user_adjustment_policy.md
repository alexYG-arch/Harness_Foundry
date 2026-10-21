# 用户调整策略

## 1. 目的

2.8 必须能适配不同的 Agent/Harness，而不能把一个通用模板强塞给所有项目。

本策略允许用户对目标包的规模、结构、术语和工程方案作合理调整，同时防止调整造成：

- authoring 与 execution 混合；
- 关键需求或细则丢失；
- 阶段、Gate 或安装边界被静默绕过；
- 自检替代独立校验；
- 文档改名后引用、Hash 或状态失真。

## 2. 调整的事实源

模型必须按以下优先级识别调整：

1. 用户在当前任务中的明确指令；
2. 用户提供并指定为权威的 PRD、设计、规则或仓库事实；
3. 用户批准的澄清答案与决策；
4. 可验证的现有工程约束；
5. 模型为继续工作而作的低风险 assumption。

第 5 类不得覆盖前四类，并必须记录。

## 3. 可调整项

用户可按目标工程调整：

- 目标类型：Agent、Agent Group、Harness、Pipeline 或混合系统；
- 项目名称、目录、语言、框架、平台和部署形式；
- Phase/Stage 的名称、数量、领域职责和交付物；
- Profile、风险级别、数据敏感度和 Human Gate；
- Contract、Rule、Skill、Validator 的组织方式；
- 外部工具、模型、Connector 和 Runtime Adapter；
- Workpack 粒度、团队角色和 Review 方式；
- 构建产物类型、隔离安装方案和目标环境；
- 文档拆分、文件名、目录名及展示语言；
- 可选的检查器、样例、报告和运维材料。

调整文件名或合并文档时，必须通过目标 START_CONTEXT 与 PACKAGE_ROLES 保留“规范角色 → 实际路径”的唯一映射。语义角色不得因改名消失。

## 4. 不得被调整掉的要求

以下内容不可通过“简化”“MVP”“单 Agent”或“先跑通再补”被静默删除：

- Authoring/Execution 隔离；
- 当前执行模式与命令授权；
- Canonical Intent 和细节保真；
- 阶段前驱条件、状态与 Lock；
- 上游变更后的影响分析与失效；
- Build Program、最终 Harness、Conformance 与 Linkage 的权责隔离；
- 真实 Runtime provenance 与自报 evidence 的区别；
- 源码入口和安装入口的来源校验；
- PASS 的证据等级与禁止过度声明；
- 用户批准、开放问题、assumption 和 deviation 的可读记录。

如用户确实要改变其中一项，模型必须将其视为 **invariant-impacting request**，停止相关部分的定稿，记录影响并请求显式决策。不得自行把它解释为普通项目适配。

## 5. 调整分类

| 分类 | 例子 | 处理 |
|---|---|---|
| A：参数化 | 名称、技术栈、目标目录、Stage 名称 | 直接适配并记录 |
| B：结构适配 | 新增 Phase、合并文档、替换构建系统 | 建立等价映射和影响说明 |
| C：不变量影响 | 跳过前驱、自动执行生成命令、让被测 Harness 自签 PASS | 阻断相关定稿，记录并请求决定 |
| D：表达调整 | 中文化、拆小文件、改表格为清单 | 调整后检查链接与语义覆盖 |

## 6. 标准调整流程

### Step 1：提取原始意图

逐条保留：

- 目标与非目标；
- MUST / MUST NOT / SHOULD；
- 否定词、限定词、单位、阈值和顺序；
- 默认值与优先级；
- 正常、错误、取消、重试、超时、权限和恢复分支；
- 外部依赖、输入、输出和责任主体。

### Step 2：建立 Intent Atom

每个重要要求必须拥有稳定 ID，并指向原始来源。不得只保存一段模型摘要。

### Step 3：形成调整差异

在目标包的 AUTHORING_DECISIONS 中写明：

- adjustment_id；
- source_ref；
- 原要求；
- 调整后表达；
- 分类 A/B/C/D；
- 理由；
- 影响的 Phase、Contract、Workpack 和验证；
- 是否需要用户批准；
- 状态与批准引用。

### Step 4：检查等价性

结构或命名变化必须回答：

- 原语义由哪个新产物承接？
- 原前驱 Gate 和证据是否仍存在？
- 是否产生新的未覆盖 Intent Atom？
- 是否使后续入口、Hash 或失效规则失真？

### Step 5：更新全链引用

至少更新：

- START_CONTEXT / PACKAGE_ROLES 引用；
- Authority Map；
- Phase Transition Graph；
- Workpack Index；
- Intent Coverage；
- Open Questions；
- Handoff Readback。

### Step 6：用户确认

满足以下任一条件时必须显式确认：

- 改变范围、责任、顺序或发布条件；
- 删除或合并必需的语义角色；
- 采用无法从输入验证的关键 assumption；
- 调整会影响数据、安全、外部系统或真实安装；
- 分类为 C。

## 7. 不完整输入的处理

模型不应因输入不完整而停掉所有低风险 authoring，但必须区分：

- **可安全假设**：命名格式、文档语言、初始目录布局；
- **必须开放**：真实目标环境、权限、生产数据、安装位置、外部凭据；
- **必须阻断**：会改变不可逆行为、安全边界或工程阶段合法性的未知项。

处理方式：

1. 保留原文；
2. 标记 assumption 或 open question；
3. 为未知项指定 owner、影响、最晚解决 Gate；
4. 不用虚构细节填空；
5. 未解决项阻断哪一阶段，必须写入状态。

## 8. Agent 与 Harness 的合理差异

目标为单 Agent 时，可减少业务 Stage 数量，但不能删除：

- 输入/输出与错误语义；
- Runtime owner；
- 工具或模型调用边界；
- provenance；
- 执行模式；
- 构建、安装、启动入口的来源区分。

目标为多阶段 Harness 时，还必须明确：

- project-level orchestrator；
- Stage 顺序和可达性；
- 各 Stage done definition；
- 跨 Stage artifact、receipt 和失败回流；
- 完整 Program Outcome，而不是局部模块集合。

## 9. 文档拆分规则

为避免大体积 Markdown：

- 每个文件只承担一个主要规范主题；
- 入口文件只做路由，不复制规范正文；
- Rule、Contract、Workflow 和 Example 分离；
- JSON 状态与机器映射不嵌入超长 Markdown；
- 相同规则只保留一个权威定义，其他文档使用相对链接；
- 拆分后必须运行链接、孤儿文件和重复权威检查。

## 10. 禁止的调整方式

- 用“本项目较简单”替代风险说明；
- 将未回答问题改写成已确认事实；
- 只保留总结，删除原子要求；
- 把 Phase 重命名后绕过其 Gate；
- 把 N/A 当作“不需要记录”；
- 为缩短文档删除失败、取消或恢复分支；
- 把示例字段当成真实 receipt；
- 因用户要求 coding 而在 authoring 会话中自动开始 coding。

## 11. 相关文档

- [用途、边界与权威](00_package_purpose_and_authority.md)
- [Authoring 工作流](02_authoring_workflow.md)
- [目标 Start Package 契约](03_target_start_package_contract.md)
- [意图保真与追踪](07_intent_fidelity_and_traceability.md)
