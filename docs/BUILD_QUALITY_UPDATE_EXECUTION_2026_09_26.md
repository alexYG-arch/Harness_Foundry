# 搭建质量更新执行记录 — 2026-09-26

范围：执行[修补与双层测试计划 v0.2](FOUNDRY_BUILD_QUALITY_REPAIR_AND_TEST_PLAN_v0_2.md)
的源码/指引/本地回归部分。基线 `7672696`；保留既有未提交的 v0.1/v0.2 计划及 Tracker 导航。
没有推送、发版、正式目标建设、模型调用或历史数据库迁移。

## 工作包结果与剩余边界

| 工作包 | 本轮落实 | 尚未证明 |
|---|---|---|
| WP0 | 当前能力与责任层核对；本轮没有优化收益主张，不做旧包/多模型比较 | 真实搭建质量是否改善 |
| WP1 | 通用政策、仓库 Skill、发行包 Skill 加入能力归属、复用优先、从交付反推计划 | Agent 实际是否遗漏/过度设计，须 B01 |
| WP2 | 加入接口推演、早期纵向切片、关键机制行为证据、完整交付停止边界；准备同版第二任务 | 两例生成 Harness 的真实组合与复用，须 B02/B03/B09 |
| WP3 | 既有返修、预算、停止、恢复及重规划回归通过；未发现需要重写控制器的复现，不改 runtime | 新包实际模型运行中的完整链路 |
| WP4 | Agent 实际 Plan 的无状态接入；首轮/最终/历史分报、版本字节核对、条件比较辅助；A10 接入既有必需测试模块 | 新 Plan 的具体 Case/修复 ID 装配须在实际文档 Review 后完成；工具不代替 Oracle |
| WP5 | 已编写并展示新版测试搭建文档，未创建 Program/目标 | 文档确认、具体运行范围批准、固定包 B01–B09、实际缺陷闭合 |

## 已有能力不是新修复

修复前的 158 项针对性回归通过。以下原有实现予以保留；测试只是局部/控制协议证据：

| 计划覆盖 | 复用的行为证据 |
|---|---|
| A01 全来源/全局约束/Review | source_intake 的完整来源与不截断；build_authoring 的 global constraints；build_review 的真实确认与漂移拒绝 |
| A02 通用计划/覆盖 | build_plan 的任务数量/ID 不专项化、遗漏需求拒绝、跨阶段依赖；build_replan 的同权限拆并与预算共享 |
| A03 合同对齐 | acceptance_contract 的元素类型错配、正常/错误对照、崩溃不是负例成功 |
| A04 调用衔接 | test_execution 与 release_acceptance_adapters 的内外 workdir、绑定解释器及真实子进程 |
| A05/A06 返修/自驱 | build_runtime 的独立消费者反馈→生产者返修、一个批准持续推进、次数不退款 |
| A07 完成停止 | 两依赖任务通过后再次 advance 无新调用；`harness_e2e_verified=false` 保留 |
| A08 恢复/分类 | 完整耐久观测恢复、部分 Case 续跑、未知/基础设施/合同缺口暂停 |
| A09 无冗余审批 | in-scope replan 无新批准；真实 Requirement/verifier/权限变化仍拒绝沿用 |

没有用“prompt 里出现某句话”的匹配测试冒充语义行为验证，没有削弱现有检查。
本次生产交付物变化主要在随包分发的搭建政策/Skill；新测试工具仅用于开发验收，
不进入通用运行包，不给所有用户工程新增两个案例、第二任务或统计比较要求。

## TDD 与测试工具变化

- 新接口的 4 项能力测试先 RED（接口未提供的明确断言，不是依赖导入错误），实现后 GREEN。
  这是新增能力，不据此声称旧控制器有 4 个生产缺陷。
- 首轮失败不被最终 PASS 覆盖；同标签但 Harness 字节变化不得计同版复用；缺有效模型信息
  不冒称条件可比；真实 Plan 原样保留，不强灌固定 H/U/E/F。
- 自检新增“尚未生成 Harness”的场景时，报告曾错误要求非空 Harness 引用，已用回归复现
  并允许显式 null，保留 NOT_READY；新版本缺测项不从旧版本 PASS 填充。该问题发生在本轮
  新工具实现中，未进入已发布包。
- 报告保留原始记录、自然/注入起因、未知 usage。它不认证宿主所提供的证据，也不输出
  整体验收 PASS。真实运行仍须独立外部业务判定，不是多做一个自签 Validator。
- 现有 source gate 已包含 `test_release_acceptance_adapters`，新增 5 项随原 CI 自动执行；
  不另建较弱 gate，不把付费模型运行加入普通 push CI。

本地日志保存在 `build/build-quality.kVFLyG/`（忽略目录，不作为他人的运行权限）：
`red.log`、`unready-red.log`、`adapters-final.log`、`source-checks-final.json`、
`full-regression.log`、`spec.json`。该目录仅保存本次诊断，不含新目标的运行记录。

## 验证状态

- 新适配器模块：16 项通过；未调用模型。
- 当前公开 source gate：245/245 通过，零跳过/失败/错误；包含本轮新增 5 项适配器测试。
- 全量历史/兼容回归：969 项，949 通过、20 项原生/本地 opt-in 跳过，零失败/错误，
  运行 859 秒。全量启动后追加的 NOT_READY 用例另在最终 16 项适配器测试及 245 项
  source gate 中通过；不将未加载的新用例计入该次 969 项。SKIP 不算已执行。
- `verify-spec`：101 个历史规范文件通过（只读基线，不是当前产品验收）。
- 仓库 Skill 校验、skill-creator 的仓库/发行模板检查通过。
  默认 Python 缺测试依赖、首个 Skill 检查环境缺 PyYAML；切换已有对应 venv 后通过，
  未改变测试断言、全局依赖或运行权限。

## 下一真实 Gate

请审阅[搭建质量 Run Test 搭建文档 v0.1](BUILD_QUALITY_RUN_TEST_BUILD_DOCUMENT_v0_1.md)。
确认内容后才准备实际 Requirement/Plan、包与具体运行范围；范围另行完整展示并取得
真实授权。不能把本次“执行更新”或源码绿色当成两项确认已经发生。
