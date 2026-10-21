# Harness Foundry v2.8 Start Package

## 定位

这是一个 **documentation-only authoring and controlled-progression guide**。

它的用途是指导模型根据用户的 PRD、约束、仓库事实和调整意见，为一个新的 Agent 或 Harness 创建目标特定的初始宪章 Start Execution Package。2.8 要求目标包同时生成三工程控制平面，使后续获批的 Build Program 能按机器 DAG、授权和硬停点受控自动推进。

本目录自身不是：

- 可执行 Agent/Harness；
- Build Program 或 Program Driver；
- Conformance Lab、校验器或认证包；
- wheel、CLI、安装包或 Release Artifact。

文档中的命令、Workpack、安装步骤和测试场景均为规范数据，不是当前执行授权。

2.8 所称“自动推进”不是无条件自启动。Authoring 必须停在人类审阅；只有批准后的 `EXECUTION_AUTHORIZATION` 才能允许 Driver 在限定模式、路径、环境、轮次和终止 Gate 内推进。真实目标安装始终需要独立授权。

## 从这里开始

首次使用按以下最小顺序读取：

1. [START_HERE](START_HERE.md)
2. [用途、边界与权威](docs/00_package_purpose_and_authority.md)
3. [用户调整策略](docs/01_user_adjustment_policy.md)
4. [Authoring 工作流](docs/02_authoring_workflow.md)
5. [目标 Start Package 契约](docs/03_target_start_package_contract.md)
6. 用户提供的目标材料

00–03 是生成目标包的最小核心集；04–16 只按当前任务追加，不要默认一次加载全部专项文档。

完整路由见[文档索引](DOC_INDEX.md)。

## 产物关系

~~~text
本 2.8 Authoring Guide
  └─指导生成→ Target-specific Start Execution Package
                    ├─生成→ Main/Lab/Linkage 三工程 Start Package
                    └─经批准与授权→ Foundry Program Driver
                                         └─按机器 DAG 自动推进至硬停点
                                              └─构建/隔离安装/联通/认证→ Certified Release
                                                   └─等待单独真实目标安装授权
~~~

任何上游文档存在，都不能替代下游的真实实现、执行、安装和证据。

## 本版解决的核心问题

- 补齐三工程机器 DAG、工程状态、版本兼容和 readiness barrier；
- 补齐 Program Driver、唯一 next action、原子状态提交、幂等与崩溃恢复契约；
- 补齐 Workpack、R/F、Finding、Repair、Invalidation、Reentry 自动 loop；
- 补齐 A/B0/C/Build/B1/Installability/Candidate/D/C4 的机器发布流水线；
- 将自动推进限制在预授权作用域内，并定义振荡、轮次、权限和真实安装硬停点；
- 将大体积协议拆为按任务最小加载的小文档；
- 将“编写目标执行包”与“执行目标执行包”彻底分离；
- 允许用户合理调整目标方案，同时保护不可弱化不变量；
- 用显式 Phase 状态机、前驱 Lock 和 N/A Lock 防止跳阶段；
- 区分 Build Program、最终 Harness、Conformance、Linkage 和安装责任；
- 要求 Intent Atom、覆盖矩阵和负向测试，防止细节与细则丢失；
- 区分真实 Codex/目标 Runtime 调用证据与 Python 自报 receipt；
- 区分源码/执行包入口与已安装 Harness 入口；
- 拆分候选发布锁与认证发布锁，消除构建、Pack、认证的循环依赖。

## 核心不变量

无论用户如何调整目标工程：

1. Authoring 不等于 Execution。
2. Registration 不等于 Harness Install。
3. Generated Commands Are Data。
4. Phase 不得静默跳过。
5. 细节不得在概括中丢失。
6. 自报证据不得证明真实 Runtime。
7. 被测 Harness 不得自我认证。
8. 源码入口不得冒充 installed entrypoint。
9. 局部 PASS 不得升级为系统、安装或发布 PASS。
10. 上游变更必须使受影响下游失效。
11. 自动推进必须有可验证授权、唯一下一动作和有界循环。
12. Authoring 审批、权限扩大、P3 N/A、设计权威变更和真实目标安装不能被自动越过。

权威定义见[用途、边界与权威](docs/00_package_purpose_and_authority.md)。

## 专项文档

| 主题 | 文档 |
|---|---|
| 包定位与权威 | [00_package_purpose_and_authority](docs/00_package_purpose_and_authority.md) |
| 用户调整 | [01_user_adjustment_policy](docs/01_user_adjustment_policy.md) |
| Authoring 流程 | [02_authoring_workflow](docs/02_authoring_workflow.md) |
| 目标包产物契约 | [03_target_start_package_contract](docs/03_target_start_package_contract.md) |
| Phase 与防跳阶段 | [04_phase_state_machine](docs/04_phase_state_machine.md) |
| Workpack、模式与命令授权 | [05_workpack_and_execution_modes](docs/05_workpack_and_execution_modes.md) |
| Agent、Codex 与 Runtime Ownership | [06_agent_and_runtime_ownership](docs/06_agent_and_runtime_ownership.md) |
| 细节保真与追踪 | [07_intent_fidelity_and_traceability](docs/07_intent_fidelity_and_traceability.md) |
| 三工程与独立 Conformance | [08_conformance_architecture](docs/08_conformance_architecture.md) |
| Build、Release 与 Install | [09_build_release_install](docs/09_build_release_install.md) |
| Linkage、修复与失效 | [10_linkage_repair_and_invalidation](docs/10_linkage_repair_and_invalidation.md) |
| 验收与负向防假通过 | [11_acceptance_and_negative_tests](docs/11_acceptance_and_negative_tests.md) |
| 参考目标包与三工程布局 | [12_reference_project_layout](docs/12_reference_project_layout.md) |
| 受控自动推进 | [13_controlled_auto_progression](docs/13_controlled_auto_progression.md) |
| 三工程机器 DAG | [14_three_project_program_dag](docs/14_three_project_program_dag.md) |
| Driver、Loop 与恢复 | [15_program_driver_loop_and_recovery](docs/15_program_driver_loop_and_recovery.md) |
| 授权与硬停点 | [16_authorization_and_hard_stops](docs/16_authorization_and_hard_stops.md) |

## 根目录辅助文件

- [PACKAGE_MANIFEST.json](PACKAGE_MANIFEST.json)：机器可读的包清单和文档角色；
- [DOC_INDEX.md](DOC_INDEX.md)：按用户任务选择最小文档集；
- [MIGRATION_MAP_v2_7_to_v2_8.md](MIGRATION_MAP_v2_7_to_v2_8.md)：从 2.7 迁移到 2.8 的自动化控制层映射；
- [CHANGELOG.md](CHANGELOG.md)：本版修正说明；
- [AUTHOR_TARGET_START_PACKAGE.md](prompts/AUTHOR_TARGET_START_PACKAGE.md)：受约束的目标包编写入口；
- [EXECUTE_CONTROLLED_BUILD_PROGRAM.md](prompts/EXECUTE_CONTROLLED_BUILD_PROGRAM.md)：批准并注册后的 Driver 受控执行入口；
- [START_PACKAGE_ACCEPTANCE.md](checklists/START_PACKAGE_ACCEPTANCE.md)：只检查目标包 authoring 完整性的清单。

## Authoring 结束状态

目标包完成结构检查后，最多可声明：

~~~text
START_PACKAGE_DRAFT_AUTHORING_CANDIDATE
START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
~~~

存在明确用户批准时，才可声明：

~~~text
START_PACKAGE_APPROVED_FOR_REGISTRATION
~~~

这些状态均不代表：

~~~text
HARNESS_EXECUTED
HARNESS_PASS
INSTALLED
CONFORMANCE_PASS
RELEASE_READY
CERTIFIED
~~~

完成目标包、Readback 与 Handoff 后必须停止。批准和注册后，可由一个有边界的 `EXECUTION_AUTHORIZATION` 允许 Driver 连续执行多个已预授权节点；遇到硬停点、授权边界、阻断 Finding、循环预算耗尽或真实目标安装时必须停止。
