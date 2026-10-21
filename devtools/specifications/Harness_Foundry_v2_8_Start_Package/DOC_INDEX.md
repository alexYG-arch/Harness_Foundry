# Harness Foundry v2.8 文档索引

## 最小必读

任何模型在生成目标 Agent/Harness Start Package 前，必须依次读取：

1. [包用途与权威](docs/00_package_purpose_and_authority.md)
2. [用户调整规则](docs/01_user_adjustment_policy.md)
3. [编写流程](docs/02_authoring_workflow.md)
4. [目标 Start Package 合同](docs/03_target_start_package_contract.md)

未读完这四份文档，不得开始生成目标包。

## 按任务加载

| 任务 | 需要加载的模块 |
|---|---|
| 设计 G0-P4 与阶段状态 | [阶段状态机](docs/04_phase_state_machine.md) |
| 编写 Workpack、命令与执行上下文 | [Workpack 与执行模式](docs/05_workpack_and_execution_modes.md) |
| 定义 Agent、Python、Codex/LLM、工具的职责 | [Agent 与 Runtime Ownership](docs/06_agent_and_runtime_ownership.md) |
| 防止需求细节、细则和限定词丢失 | [意图保真与追溯](docs/07_intent_fidelity_and_traceability.md) |
| 设计 Main/Lab/Linkage 三工程 | [Conformance 架构](docs/08_conformance_architecture.md) |
| 设计构建、Pack、认证与安装 | [构建、发布与安装](docs/09_build_release_install.md) |
| 设计失败回流与下游失效 | [联通、修复与失效](docs/10_linkage_repair_and_invalidation.md) |
| 设计必杀负例和最终验收 | [验收与负向测试](docs/11_acceptance_and_negative_tests.md) |
| 查看目标目录和产物分工 | [参考工程布局](docs/12_reference_project_layout.md) |
| 设计批准后的受控自动推进 | [受控自动推进](docs/13_controlled_auto_progression.md) |
| 设计 Main/Lab/Linkage 机器 DAG 与 barrier | [三工程机器 DAG](docs/14_three_project_program_dag.md) |
| 设计 next-action、loop、幂等和崩溃恢复 | [Program Driver、Loop 与恢复](docs/15_program_driver_loop_and_recovery.md) |
| 设计执行授权、升级和硬停点 | [授权与硬停点](docs/16_authorization_and_hard_stops.md) |

## 直接使用

- [模型编写指令](prompts/AUTHOR_TARGET_START_PACKAGE.md)
- [批准后的受控执行指令](prompts/EXECUTE_CONTROLLED_BUILD_PROGRAM.md)
- [Start Package 验收清单](checklists/START_PACKAGE_ACCEPTANCE.md)
- [目标包模板目录](templates/target_start_package/README.md)
- [三工程独立启动模板](templates/project_start_packages/)
- [v2.7 到 v2.8 迁移映射](MIGRATION_MAP_v2_7_to_v2_8.md)

## 加载原则

- 不要一次加载全部文档；按当前工作加载最少模块。
- 生成目标包时，模板是结构起点，不是业务事实源。
- 用户提供的 PRD、白皮书、规则、现有工程和明确决定必须进入目标包的 canonical source set。
- 文档中出现的命令默认是声明性数据；只有目标 Workpack 的结构化 Command Manifest 才能授权执行。
- 自动推进模块只在设计获批后的执行控制层时加载；它们不改变 Authoring 必须停止的规则。
