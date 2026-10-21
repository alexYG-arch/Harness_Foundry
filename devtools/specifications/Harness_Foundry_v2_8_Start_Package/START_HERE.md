# START HERE

## 1. 当前要做的事

使用本包时，先把任务表达为：

> 在 BUILD_PROGRAM_AUTHORING 活动中使用 AUTHORING_ONLY 执行模式，根据指定目标材料创建或修订一个目标特定的初始宪章 Start Execution Package；完成 authoring 检查、Readback 和 Handoff 后停止。

如果用户要求“创建新的 Agent/Harness”，本包在当前轮承担的是 **创建工程建设起点**，不是自动把 Agent/Harness 编码、安装并运行完毕。

但 2.8 生成的目标包不得只停留在计划文字：它还必须包含批准后可由 Program Driver 消费的三工程 DAG、发布流水线、授权、loop、修复、失效和恢复资产。Authoring 当前不执行这些资产。

## 2. 先锁定当前模式

进入 authoring 前明确：

~~~text
authoring_activity = BUILD_PROGRAM_AUTHORING
execution_mode = AUTHORING_ONLY
generated_commands_are_data = true
auto_start_generated_workpacks = false
execution_started = false
install_started = false
certification_started = false
~~~

允许的动作：

- 读取用户材料和仓库事实；
- 在声明的目标包目录中写文档与机器可读状态；
- 执行只读检查以及 JSON、链接、引用等 authoring 检查。

当前不允许：

- 运行新生成的 Workpack；
- 启动 Program Driver；
- coding 最终 Agent/Harness；
- 构建、安装、迁移、部署或启动服务；
- 调用目标 Runtime 后签发真实执行结论；
- 运行认证或生成 Release Lock。

## 3. 最小读取顺序

所有目标包生成任务在写入前必须读完：

1. [用途、边界与权威](docs/00_package_purpose_and_authority.md)
2. [用户调整策略](docs/01_user_adjustment_policy.md)
3. [Authoring 工作流](docs/02_authoring_workflow.md)
4. [目标 Start Package 契约](docs/03_target_start_package_contract.md)
5. 用户指定的原始材料

然后按任务追加：

| 用户任务 | 追加读取 |
|---|---|
| 定义 Phase、Gate、Lock | [阶段状态机](docs/04_phase_state_machine.md) |
| 拆 Workpack、命令和模式 | [Workpack 与执行模式](docs/05_workpack_and_execution_modes.md) |
| 定义 Agent、Codex 或 Runtime 责任 | [Agent 与 Runtime Ownership](docs/06_agent_and_runtime_ownership.md) |
| 保留 PRD 细节和细则 | [意图保真与追踪](docs/07_intent_fidelity_and_traceability.md) |
| 设计三工程和独立认证 | [Conformance 架构](docs/08_conformance_architecture.md) |
| 设计构建、发布和安装 | [Build、Release 与 Install](docs/09_build_release_install.md) |
| 设计联通、修复和重建 | [Linkage、修复与失效](docs/10_linkage_repair_and_invalidation.md) |
| 设计验收和假通过防护 | [验收与负向测试](docs/11_acceptance_and_negative_tests.md) |
| 设计批准后的自动推进范围 | [受控自动推进](docs/13_controlled_auto_progression.md) |
| 设计三个工程的搭建/安装 DAG | [三工程机器 DAG](docs/14_three_project_program_dag.md) |
| 设计 Driver、循环、恢复和重入 | [Driver、Loop 与恢复](docs/15_program_driver_loop_and_recovery.md) |
| 设计授权和不可自动越过的门禁 | [授权与硬停点](docs/16_authorization_and_hard_stops.md) |

需要完整导航时使用[文档索引](DOC_INDEX.md)，而不是盲目加载所有文件。

要直接开始生成，可在读完必需规范后使用[目标包 Authoring Prompt](prompts/AUTHOR_TARGET_START_PACKAGE.md)；它仍受本页模式与停点约束。

已批准并完成 Registration 的目标包才可使用[受控 Build Program 执行 Prompt](prompts/EXECUTE_CONTROLLED_BUILD_PROGRAM.md)。该 Prompt 不能用于 Authoring Candidate，也不能签发真实目标安装授权。

## 4. 输入检查

开始写入前确认：

- target_id / target_name；
- target_type：Agent、Harness 或混合系统；
- 原始材料及其权威顺序；
- 目标包绝对路径；
- 源目录与目标目录的读写边界；
- 已知技术、平台、安全、数据和安装约束；
- 用户要求的调整；
- 当前明确禁止的动作。
- 后续希望自动推进到哪个 Gate、允许哪些模式、最大轮次和必须人工处理的决定。

未知项分为：

- 低风险 assumption：可记录后继续；
- open question：指定 owner 与最晚解决 Gate；
- blocker：会改变权限、安全、真实环境或阶段合法性，必须暂停相关部分。

## 5. 固定 Authoring 顺序

### A. 确认真实根与源材料

不要假设当前目录就是最终工程根。源材料默认只读，输出写入独立目标包目录。

### B. 提取 Canonical Intent

保留目标、非目标、MUST、MUST NOT、条件、顺序、阈值、默认值、错误、取消、重试、超时、权限和恢复路径。

### C. 记录用户调整

按[用户调整策略](docs/01_user_adjustment_policy.md)分类为参数化、结构适配、不变量影响或表达调整。禁止用“合理优化”掩盖需求删除。

### D. 生成 Charter 与 Profile

先确定 Program Outcome、边界、ownership 和完成声明，再设计阶段和 Workpack。不要从一个通用目录树反推用户需求。

### E. 建立阶段状态机

每个 Phase 必须有 entry criteria、前驱 Lock、Gate、output Lock 与 allowed next phase。不适用阶段必须有 N/A Lock，不能直接跳过。

### F. 建立 Intent、Contract 与验证映射

每条 MUST 都要映射到 owning artifact、Phase/Workpack、验证模式、证据和 return path。真实 Runtime 证据不能由被测代码自行填写后成立。

### G. 生成首批 Workpack

首个 Workpack 默认用于 G0 或等效控制基础。Workpack 中的命令保持 declarative，当前会话不执行。

### H. 做 Authoring 检查

只检查目标包结构、链接、JSON、ID、引用、覆盖、Phase 前驱和命令声明状态。不得将结果升级为 Harness PASS。

### I. Readback、Handoff、停止

重新读取实际文件，列出缺口和第一个合法后续动作，写入 AUTHORING_STOP。

## 6. 四个不得混淆的“开始”

| 名称 | 含义 | 当前包是否执行 |
|---|---|---|
| Start Package Authoring | 编写工程建设起点 | 是 |
| Build Program Registration | 装载已批准目标包，auto-start=false | 否 |
| Workpack Execution | 在单独模式和命令授权下 coding | 否 |
| Controlled Auto Progression | Driver 在有效授权范围内连续选择唯一下一动作 | 否；只生成控制契约 |

“注册完成”不等于“Harness 已安装”；“首个 Workpack 可执行”也不等于“当前已获执行授权”。

## 7. 创建目标包时必须产出

至少包含这些语义角色：

- README、START；
- PROGRAM_CHARTER、TARGET_PROFILE；
- START_CONTEXT、Authority/Execution Boundary；
- Canonical Intent、Intent Atoms、Coverage Matrix；
- Phase Transitions、Program State、Roadmap；
- Contract 与 Validation/Review Plan；
- Workpack Index、首个 Workpack 与 Capsule；
- 三工程 Program Manifest、工程 DAG、Release Pipeline；
- Program Driver Contract/State、Automation/Authorization Policy；
- Workpack Result、Loop State、Finding、Repair、Invalidation 与 Reentry；
- Main、External Lab、Read-only Linkage 各自的 Start Package；
- Authoring Decisions、Open Questions、Authoring Handoff。

默认路径与字段见[目标包契约](docs/03_target_start_package_contract.md)，参考落盘结构见[参考工程布局](docs/12_reference_project_layout.md)。

## 8. Authoring 停点检查

结束前逐项回答：

- 是否仍有未映射 Intent Atom？
- 是否存在无前驱 Lock 的 Phase 跳边？
- 是否把 N/A 写成了“直接省略”？
- 是否把命令示例变成当前执行授权？
- 是否把 Build Program driver 写成 final Harness entrypoint？
- 是否用 mock、自报 receipt 或 Python 日志证明真实 Runtime？
- 是否把 Linkage PASS 写成 Conformance PASS？
- 是否把 isolated install 写成 real target install？
- 是否把 touched Phase 写成 closed Phase？
- 是否实际重新读取了目标包？
- 是否缺少三工程机器 DAG、唯一 next action 或受控 auto-progress 停点？
- 是否把 real target install 写入了可自动越过的授权范围？

任一问题为“是”时，目标包不得进入 READY_FOR_USER_REVIEW。

## 9. 唯一合法的本轮结束语义

完成时声明：

~~~text
START_PACKAGE_DRAFT_AUTHORING_CANDIDATE
或
START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW

AUTHORING_STOP
execution_started = false
install_started = false
certification_started = false
~~~

之后等待用户对目标包进行审阅、调整或另行授权下一阶段。

批准后的执行边界见[受控自动推进](docs/13_controlled_auto_progression.md)与[授权和硬停点](docs/16_authorization_and_hard_stops.md)。这些后续规则不能反向取消本页的 Authoring Stop。
