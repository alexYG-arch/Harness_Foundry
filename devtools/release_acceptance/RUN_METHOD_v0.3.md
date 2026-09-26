# 搭建质量独立 Run Test 方法 v0.3

状态：开发工具已接入；真实运行尚未开始。本文不授予模型、目标、预算或发布权限。
它补充修补计划 v0.2 的 B 层；v0.2 固定阶段夹具保留作运行器回归，不冒充方案推理评估。

## 从材料进入，不从答案进入

宿主先从公开 PRD/项目说明完成问答及版本化搭建文档，展示后取得真实 Review。
随后由 Agent 推导 Requirement/Plan；阶段 ID、数量、内部设计均由需求决定，
不得先调用 `prepare.proposal()` 再声称测试了自主规划。沿用通用公开入口和现有独立检查。

开发调用 `prepare.authored_proposal(request, scope)` 仅复用原编译器/独立静态校验器，
原样返回两个输入的独立副本，不创建 Program、写目录、运行命令或准备批准。
`scope_validated=false`、`semantic_coverage_verified=false`：实际文档绑定/权限准备仍在
公开入口，来源到需求的语义映射由宿主核对。不得把此工具的成功当人工 Review。
运行前展示实际 Plan、包、读写域、工具/模型、检查器、有限预算/期限及具体故障安排。

## 原观察器的复用边界

复用 `exercise.task_observations`、`csv_observations` 收集真实输出，独立调用
`verify.task_report`、`csv_report` 对照公开业务合同。生成 Harness 的检查结果只是其中
一项观察，不能充当最终业务 Oracle。正常、错误业务和异常检查器分别验证。

`verify` 的旧阶段分派与修复 ID（H-2/U-0 等）仅属于固定 Plan 回归夹具；新 Plan 的
宿主检查入口必须按实际产物/Case 映射它们。不得在一个任务 ID 变化后仍投递旧责任人，
也不得将单纯重试观察器当模型实施修复。

`exercise.main()` 的首次错误副本、之后恢复真实 app 是旧观察恢复回归，不作为 B05 的
真实模型修复证据。B05/B09 使用新 Plan 声明的一次性业务副本，独立拒绝后由有写域的
CODEX 生产者修改它；观察器不得自行撤除故障。原输入、已验收应用和 Harness 不被注入。

## 记录与报告 API（开发测试工具，不进入发行包）

`quality_report.summarize(evaluations, required_scenarios, reuse_uses=(), comparison=None)`
生成描述性报告，没有总 PASS、批准或发布副作用。宿主按真实顺序提供独立外部观测：

- 每轮含 `evaluation_ref`、`package_ref`、`harness_ref`、`results`（场景到真实状态）
  与 `evidence_refs`（原始命令/事件/报告位置）。构建未就绪时 `harness_ref=null`，不能删案例。
- 第一轮是首次下游使用、尚未利用该次反馈的版本，不是模型第一次代码输出；末轮是当前
  最终版本。首轮、历史、末轮分别保留，不能将旧版本 PASS 并入新版本未测项。
- 未测场景为 NOT_RUN；NOT_READY、FAIL、BLOCKED、NOT_EXERCISED 等按实际记录，
  不统一映射成失败或成功。未得到 usage 保持 null/缺失，不能填零。
- 宿主保留构建/使用/修复耗时、原始 usage、自然/注入起因、责任层，以及关键机制
  的声明、实际触发事件和业务作用记录。报告保留这些字段，不替宿主伪造因果结论。

同版复用的 `reuse_uses` 是最终版本的两个已预定任务，分别记录 `task_id`、
`task_kind`、`session_ref`、`package_ref`、`harness_ref`、外部 `result/evidence_refs`。
不能用两组数据或两个命令改名为两项开发任务。

每次使用前后由宿主调用 `capture_harness(root, files)`，记录在 `harness_before/after`。
files 在运行前明确列出固定规则/脚本/配置，不包含允许变化的业务输出/检查点。
它只读取少量声明文件的字节并编码成 JSON，不建立 Hash 链或扫描全部工作树。
同名版本但字节变化、会话/任务不独立、任一外部结果失败或没有证据，均不能标为 OBSERVED。
OBSERVED 是所提供观测的匹配结果，不认证这些输入；原始真实会话与外部观察仍须核对。
若新版本需要重测，保留旧记录并为该版取得两项任务证据，不跨版本拼接、不重置预算。

`comparison_summary(before, after)` 仅供确需优化主张时使用；没有比较默认 NOT_REQUESTED。
条件明确绑定 contract/inputs/executor/tools/permissions/checker/budget。
executor 记录 requested_model/effective_model/client_version，以及可获得的 service_revision。
缺失实际配置或条件不同为 NOT_COMPARABLE；服务内部版本未知明确列为限制。
条件一致也只标 MATCHED_OBSERVABLE_CONDITIONS，不自动判性能提升；构建者信息、实际
结果/成本和有限复跑安排仍由宿主报告。普通违约修复无需旧版比较或性能门槛。

## Run Test 的顺序与停止

B01 语义映射 → 首轮建设/使用 → 必需的组合、留出数据、真实修复、恢复与第二任务
→ 最终覆盖核对 → B07 完成与再次推进。B09 在最终停止前完成，不重开已完成任务追加义务。
基础设施故障不假扮业务失败；新的范围内失败回流最小 A 回归后复验。
达到约定交付即停止；具体预算耗尽、权限失效、未知副作用及合同决定才是中途真实 gate。
本轮不声称效率提升，不默认安排旧包/新包或多模型比较。
