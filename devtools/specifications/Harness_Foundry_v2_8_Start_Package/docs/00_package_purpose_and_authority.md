# 2.8 文档包的用途、边界与权威

## 1. 文档状态

本文定义 Harness Foundry v2.8 Start Package 的顶层定位与权威规则。

规范词：

- MUST / 必须：不可省略的要求；
- MUST NOT / 禁止：不可执行或不可声明的行为；
- SHOULD / 应：默认遵循，偏离时必须记录理由；
- MAY / 可：目标项目可按需要采用。

## 2. 一句话定位

Harness Foundry v2.8 是一个 **documentation-only authoring and controlled-progression guide**：

> 它指导模型根据用户意图，为一个新的 Agent 或 Harness 编写目标特定的初始宪章 Start Execution Package，并把批准后的三工程搭建、coding、构建、隔离安装、联通、认证和修复路径表达为机器可控流程。

本包自身不是：

- Agent 或 Harness；
- Build Program；
- 可执行的 Start Execution Package；
- Conformance Lab、校验器或测试包；
- 安装包、wheel、CLI 或运行时；
- Release Artifact、Certificate 或 Release Lock。

目录中存在流程、命令示例、JSON 示例或验收要求，不代表这些内容已经实现或被执行。

## 3. 必须区分的五个对象

| 对象 | 职责 | 不得被误称为 |
|---|---|---|
| 2.8 Authoring Guide | 指导如何编写目标包和受控推进契约 | 可执行 Harness、校验包、运行中 Driver |
| Target Start Execution Package | 描述目标工程的宪章、边界、阶段、Workpack 和接口 | 已启动 Build Program |
| Registered Build Program | 在单独授权下装载目标包并管理工程建设 | 已安装的最终 Harness |
| Target Agent / Harness | 由工程建设产生的真实实现与运行入口 | Build Program 或执行包目录 |
| External Conformance / Linkage System | 独立检查已构建、已安装候选物及其接口与证据 | 被测 Harness 的自检脚本 |

这些对象的代码根、状态、入口、证据与权限必须可区分。任何文档不得使用“执行包已完成”推导“Harness 已可运行”。

## 4. 本包可做与不可做

本包可指导模型：

- 读取用户提供的 PRD、说明、仓库事实和约束；
- 提取 Canonical Intent 与 Intent Atom；
- 创建目标 Program Charter、Target Profile 和 Authority Map；
- 设计显式阶段图、前驱 Gate、Lock、Workpack 和 Capsule；
- 声明未来可执行命令、验收方式、证据与回流条件；
- 生成可交给工程 coding 会话的初始目标包；
- 生成三工程 DAG、Release Pipeline、Driver、Authorization、Loop 和 Recovery 契约；
- 生成 Main、Lab、Linkage 各自的独立 Project Start Package；
- 在用户允许的范围内调整文档结构和目标工程方案。

使用本包进行 authoring 时禁止：

- 执行刚生成的 Workpack、安装器、迁移、部署或服务启动命令；
- 把 Markdown 中的命令当成当前 shell 授权；
- 注册或启动 Build Program；
- 构建、安装或运行目标 Agent/Harness；
- 调用目标 Runtime 并伪称已产生运行证据；
- 运行外部认证并签发 PASS、Certificate 或 Release Lock；
- 因“顺手验证”扩大当前写入或副作用边界。

Authoring 期间只可执行当前会话明确允许的只读检查和 authoring 检查，例如 Markdown 链接检查、JSON 语法检查、目录清单检查与重新读取。

## 5. 权威顺序

默认权威顺序为：

~~~text
适用法律、安全要求与平台硬约束
→ 当前用户的明确目标、授权、禁止事项与已批准调整
→ 本 2.8 文档包的不可弱化不变量
→ Approved Target Program Charter
→ Locked Target Profile
→ Locked Contract / Rule / Projection / Review Rule
→ Phase Transition Plan
→ Workpack / Capsule / Command Manifest
→ Candidate Implementation
~~~

解释规则：

1. 下层不得静默改写上层。
2. 用户的新指令与旧材料冲突时，记录冲突和采用依据。
3. 未批准的模型推断只能标记为 assumption，不得伪装为用户要求。
4. 如用户要求影响不可弱化不变量，按[用户调整策略](01_user_adjustment_policy.md)处理，不得静默降级。
5. 目标包获批后，其 Charter、机器 DAG 和授权是运行控制输入；2.8 文档包不替目标项目签发运行期 PASS。

## 6. 不可弱化不变量

无论目标是单 Agent、Agent Group、Pipeline 或 Harness，以下要求必须保留：

1. **Authoring 不等于 Execution。** 生成内容中的指令默认是数据。
2. **Build Program 注册不等于 Harness 安装。** 注册不得自动启动 Workpack。
3. **阶段不可静默跳过。** 不适用阶段必须有显式 N/A 决策、理由、批准和等效前驱证明。
4. **上游变更必须使受影响下游失效。** 不能只看文件是否存在。
5. **细节必须可追踪。** 关键限定、否定、单位、顺序、默认值、异常和恢复分支不得在概括中丢失。
6. **每条 MUST 必须有 machine、human 或 hybrid 验证方式。**
7. **计划、样例和自报 receipt 不能证明真实 Runtime 执行。**
8. **被测对象不得自我认证。** Linkage、Conformance 与建设/修复权必须分离。
9. **源码执行包入口不得冒充已安装 Harness 入口。**
10. **局部 PASS 不得聚合成系统、安装或发布 PASS。**
11. **自动推进必须有唯一 next action、有效授权、有界 loop 和可恢复 Ledger。**
12. **Authoring、人类设计决定、权限扩大和真实目标安装是硬停点。**

## 7. 允许的状态与声明

本 2.8 文档包自身最多可被描述为：

- DOCUMENTATION_ONLY；
- AUTHORING_GUIDE_AVAILABLE；
- STRUCTURALLY_REVIEWED（仅在实际完成文档结构检查后）。

目标包在 authoring 结束时最多可被描述为：

- START_PACKAGE_DRAFT_AUTHORING_CANDIDATE；
- START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW；
- START_PACKAGE_APPROVED_FOR_REGISTRATION（仅有明确批准时）。

仅凭本包或目标包，禁止声明：

- HARNESS_EXECUTED；
- HARNESS_PASS；
- CONFORMANCE_PASS；
- INSTALLED；
- RELEASE_READY；
- CERTIFIED。

## 8. 与 v2.7 的关系

2.8 继承 2.7 的 Authoring 边界并补齐受控自动推进控制面，不是对某个已实现 Runtime 的升级证明。

- 新任务明确选择 2.8 时，authoring 和控制面规则以本包为准；
- 2.7 可作为历史设计来源，但不能用自然语言流程替代 2.8 机器资产；
- 被 2.7 修正的顺序、权责或声明问题不得因加入自动化而恢复；
- 既有 2.7 目标包迁移时，应通过显式迁移映射和负向验收，而不是改版本号后宣称完成。

## 9. Authoring 的终点

当[目标包契约](03_target_start_package_contract.md)规定的产物已生成、仅 authoring 范围的检查已完成、Readback 与 Handoff 已写入后，本轮必须停止。

下一步如需注册、coding、执行、构建、安装或认证，必须取得明确授权。批准后的同一授权可覆盖一组有界节点，但不能覆盖本包定义的硬停点。

## 10. 相关入口

- [包入口](../START_HERE.md)
- [用户调整策略](01_user_adjustment_policy.md)
- [Authoring 工作流](02_authoring_workflow.md)
- [目标 Start Package 契约](03_target_start_package_contract.md)
- [阶段状态机](04_phase_state_machine.md)
- [Workpack 与执行模式](05_workpack_and_execution_modes.md)
- [受控自动推进](13_controlled_auto_progression.md)
- [授权与硬停点](16_authorization_and_hard_stops.md)
