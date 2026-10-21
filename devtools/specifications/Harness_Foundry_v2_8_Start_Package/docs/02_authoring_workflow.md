# 目标 Start Execution Package 的 Authoring 工作流

## 1. 工作流目标

本工作流把用户材料转化为一个目标特定、可审阅、可注册但尚未执行的初始宪章 Start Execution Package。

最终结果服务于后续工程 coding。它不在本轮启动 coding、运行 Harness、安装产物或认证结果。

## 2. Authoring 会话声明

开始前必须明确：

~~~text
authoring_activity = BUILD_PROGRAM_AUTHORING
execution_mode = AUTHORING_ONLY
generated_commands_are_data = true
auto_start_generated_workpacks = false
execution_started = false
install_started = false
certification_started = false
~~~

当前会话的允许写入路径仅限用户指定的目标包目录。源 PRD、现有仓库、2.8 文档包和外部系统默认只读。

## 3. 输入最低集

开始 authoring 至少需要：

- 目标名称或临时 ID；
- 目标类型：Agent 或 Harness；
- 用户目标、非目标与已知交付形式；
- 输入材料的位置或正文；
- 目标包写入目录；
- 可确认的技术、环境和安全约束。

缺失项应写入 Open Questions；高风险未知项不得由模型补造。

## 4. 最小加载路由

模型不应默认把所有文档一次性塞入上下文。

### 路由 A：首次定向

读取：

1. [包用途与权威](00_package_purpose_and_authority.md)
2. [用户调整策略](01_user_adjustment_policy.md)
3. 本 Authoring 工作流
4. [目标包契约](03_target_start_package_contract.md)
5. 用户指定的原始材料

### 路由 B：用户要调整模板或方案

核心集之外，只追加读取与调整项直接相关的专项文档。

### 路由 C：设计阶段和 Workpack

追加读取：

- [阶段状态机](04_phase_state_machine.md)
- [Workpack 与执行模式](05_workpack_and_execution_modes.md)
- [Agent 与 Runtime Ownership](06_agent_and_runtime_ownership.md)

### 路由 D：设计验证、安装与认证接口

按需读取：

- [意图保真与追踪](07_intent_fidelity_and_traceability.md)
- [Conformance 架构](08_conformance_architecture.md)
- [Build、Release 与 Install](09_build_release_install.md)
- [Linkage、修复与失效](10_linkage_repair_and_invalidation.md)
- [验收与负向测试](11_acceptance_and_negative_tests.md)

### 路由 E：设计批准后的自动推进

追加读取：

- [受控自动推进](13_controlled_auto_progression.md)
- [三工程机器 DAG](14_three_project_program_dag.md)
- [Program Driver、Loop 与恢复](15_program_driver_loop_and_recovery.md)
- [授权与硬停点](16_authorization_and_hard_stops.md)

## 5. Step 0：确认真实边界

在写文件前：

1. 确认真正的工作根和目标包根；
2. 列出源材料并声明只读/可写属性；
3. 检查是否存在同名目标目录及用户已有更改；
4. 确认只创建目标 Start Package，而不是直接改最终工程；
5. 写明当前不授权执行、安装或联网的动作。

如果目标包会覆盖用户内容，必须先停止并请求决定。

## 6. Step 1：建立 Canonical Intent

不得先套模板再压缩用户需求。

先生成：

- 来源清单；
- 原始要求的稳定引用；
- Intent Atom；
- 冲突、重复、未知和 assumption；
- 初始 coverage mapping。

关键细节包括否定、条件、顺序、阈值、单位、默认值、角色、错误和恢复路径。

## 7. Step 2：选择 Target Profile

Target Profile 至少回答：

- 是 Agent、Harness 还是混合系统；
- 单进程、多 Stage 还是外部 orchestrator；
- Primary Runtime 和外部工具是什么；
- 数据、安全、联网和权限边界；
- 本地、服务、容器或桌面运行形态；
- 构建和安装产物的预期形式；
- 哪些能力由项目提供，哪些能力属于外部系统；
- 哪些完成声明需要真实 Runtime 或独立认证。

无法确认的字段标记 UNKNOWN，不得填入看似合理的虚构值。

## 8. Step 3：编写 Program Charter

Charter 必须包含：

- Mission；
- Program Outcome；
- Scope / Non-goals；
- Authority；
- Roles 与 ownership；
- 目标阶段和退出条件；
- Canonical Artifact；
- Evidence 与 Review 原则；
- Change、Invalidation 与 Return Path；
- Completion Claim 边界；
- 已批准的调整与例外。

Charter 不复制全部 Contract 或 Workpack 正文，只引用其权威路径。

## 9. Step 4：设计阶段状态机

阶段图必须是显式、有前驱的有向状态转换：

- 每个 Phase 定义 entry criteria、done definition、Gate 和 Lock；
- 下一 Phase 必须引用有效前驱 Lock；
- 禁止直接从 P2 跳到 P4；
- 不适用 Phase 必须生成经批准的 N/A Lock；
- 同时记录 highest_touched_phase 与 highest_locally_closed_phase；
- 上游变化必须确定下游失效面。

具体规则见[阶段状态机](04_phase_state_machine.md)。

## 10. Step 5：定义 Contract、Rule 与验证

每项 Program Outcome 和 MUST 都必须映射到：

- owning artifact；
- owning Phase / Workpack；
- machine、human 或 hybrid 验证；
- 正向和负向场景；
- 失败状态和 return path；
- 所需证据及其生产者；
- 不能由当前阶段证明的声明。

Validator 检查结构不等于 Human Review；样例通过不等于真实运行通过。

## 11. Step 6：拆分 Workpack 与 Capsule

首批 Workpack 应足以开始 G0 或等效控制基础，但不得跨阶段预做后续实现。

每个 Workpack：

- 只承担一个可闭合 coding objective；
- 声明依赖、允许写路径和 expected outputs；
- 区分 review_mode 与 execution_mode；
- 使用结构化 Command Manifest；
- 声明 validation、readback、side effects 和 cleanup；
- 定义完成、阻断和 return conditions；
- 携带最小 Capsule，不依赖整个聊天上下文。

## 12. Step 7：生成目标包

按[目标包契约](03_target_start_package_contract.md)写入：

1. 入口与 Charter；
2. Context、Authority 与 Profile；
3. Intent、阶段和状态；
4. Contract、验证和首批 Workpack；
5. Decisions、Questions 与 Handoff。

同时实例化三工程 DAG、Release Pipeline、Driver/Authorization/Loop/Repair/Invalidation/Reentry 机器资产，以及三个工程各自的 Project Start Package。它们保持 `PLANNED_NOT_STARTED`，不能因生成完成而进入执行状态。

大段主题应拆为小文档；机器状态使用 JSON；同一规则不得复制成多个权威正文。

## 13. Step 8：只做 Authoring 检查

允许的检查：

- 文件存在性和 START_CONTEXT / PACKAGE_ROLES 引用一致性；
- Markdown 相对链接；
- JSON 可解析性与 schema 字段完整性；
- ID、引用和路径唯一性；
- Intent Atom 覆盖；
- Phase 前驱闭包；
- Workpack 依赖闭包；
- 所有命令均处于 declarative 状态；
- 状态文件声明 execution_mode=AUTHORING_ONLY 且 execution_started=false；
- Readback 与输入清单一致。
- 三工程和发布 DAG 拓扑唯一、无非法跳边；
- Driver 可计算唯一 next action，并能在硬停点返回结构化 WAITING 状态；
- Command、Authorization、Loop 和 Recovery 字段满足 2.8 机器契约；
- 普通执行授权不能包含 `REAL_TARGET_INSTALL`。

这些检查的结论只能是目标包 authoring 状态，不得升级为 Harness、Runtime 或 Conformance PASS。

## 14. Step 9：Readback、Handoff 与停止

重新读取关键产物并输出：

- 创建/修改文件清单；
- 已覆盖 Intent Atom 和未覆盖项；
- 已批准调整、assumption 和 open questions；
- 第一个合法的后续动作；
- 后续动作所需 execution mode、授权和环境；
- 明确的停止声明 START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW 或带 blocker 的 draft 状态。

随后停止。不得因目标包中写有下一步命令而执行它。

## 15. 需要暂停的条件

出现以下情况，停止受影响部分并记录：

- 目标根或写入范围不明确；
- 用户材料互相冲突且会改变范围或安全边界；
- 真实安装、生产环境或凭据被隐含要求；
- 用户要求跳过前驱阶段但没有 N/A 决策；
- 被测系统被要求自签认证；
- 无法区分 source entrypoint 与 installed entrypoint；
- 关键 Intent Atom 没有 owner、验证或 return path。

## 16. 禁止的流程捷径

- 生成 Workpack 后立即运行；
- 用一次全仓测试代替逐项 Intent 验证；
- 先写 P1、P2、P4，之后“有空再补 P3”；
- 用 Python 自行构造 receipt 证明调用过目标 Runtime；
- 在目标源码目录中完成所谓隔离安装验收；
- 把执行包目录里的 driver 当作最终 Harness CLI；
- 将 open question 删除后宣称需求已闭合。
