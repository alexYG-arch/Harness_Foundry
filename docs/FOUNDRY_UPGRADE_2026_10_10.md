# Foundry 能力与稳定性升级：源码交付记录

> 本文保留首次源码实施的历史快照。下文“真实模型未运行”“G5R/G5E NOT_RUN”等表述
> 只描述该阶段；后续评测、定向修复和当前交付状态见开发仓库的
> `docs/FOUNDRY_UPGRADE_EVALUATION_2026_10_10.md`（该评测摘要不随运行包分发）。
> 旧验证数字不改写为最新代码结果；下文“尚未推送或发布”只描述首次实施阶段。
> 这些实现现已纳入 v0.3.0，当前限定证据发布范围见
> [在线发布说明](https://github.com/alexYG-arch/Harness_Foundry/releases/tag/v0.3.0)。

本轮执行用户确认的 2026-10-10 升级计划。起点是 `a580ae3d1b2982e15ee2c2690670e00acd59f047`。
范围为通用 Foundry 源码、离线测试和文档；不是旧 Harness 搭建流程。没有改 AICut、历史
Candidate/运行库、A3、已发布 ZIP，没有真实模型运行、动态攻防、安装、提交或发布。

## 实施与 Gate

| 步骤 | 本轮增量 | Gate 与证据边界 |
|---|---|---|
| S0 / WP00–01 | 当前架构与历史 41 能力分开；将验收前置、输入串用、误删、设施故障转成确定性临时回归 | 新字段旧版不支持属于能力新增，不伪报为既有行为缺陷；未重放 AICut 历史服务 |
| S1 / WP02–03 | 来源语义归类指导；Plan 1.1 声明 Case 前置和证据 Job，编译即检查可满足性 | 检查显式关系；不能证明全部自然语言语义 |
| S2 / WP04–05 | 同解释器/工作目录/只读接收器预检；phase、耗时、最新输出和预算诊断；事件订阅先于动作的有界观察示例 | 设施失败不派发业务实施；进程存活/有输出不算验收成功 |
| S3 / WP06–08 | 正式 accepted 输入包；公开文件效果契约；实施前 baseline、独立检查后效果比较再 CAS | 不另建控制库；只保证声明的本地观测范围，拒收不是回滚 |
| S4 / WP09–10 | 失败摘要与原 attempt 引用；恢复共用效果判定；重规划保留批准契约 | 不重做已完成实施、不退款预算、不串历史版本；已有分支机制复用 |
| S5 / WP11 | 接入现有 source gate 和开发包依赖清单 | 源码/临时包结果与正式固定提交包分开记录 |
| S5 / WP12–13 | 复用既有真实双案例适配器；新增 2×2 描述性报告 | 新版真实实用 G5R、收益 G5E 为 NOT_RUN，不能继承旧包结果 |
| S6 / WP14 | 架构、CLI、运行、Skill 与 AICut 采用差异说明 | AICut 只交采用方案，未改代码或状态 |
| WP15 | 确定性缓存 | DEFERRED：没有测量证明值得新建缓存 |

## Plan 1.1 公开增量

旧 `schema_version: "1.0"` 继续可读/执行，不自动迁移；新 Workpack 字段只有 `1.1` 接受，
其他未知 Plan/Workpack 字段仍拒绝。不增加人工 Hash 或逐任务审批。

- Case 可声明 `required_artifact_ids`：必须是本 Workpack 输出或已声明 ARTIFACT 输入。
  下游/隐式输入不能提前用于上游验收。`acceptance_stage` 如存在须等于验证者 Job ID。
- Workpack 可声明 `environment: {"python":"python", "modules":["json"], "paths":["input/data.json"]}`。
  python 是批准工具别名，modules 是顶层模块名，paths 是工作区相对路径。预检用该解释器
  的 `-I -B` 模式、同 cwd、现有只读沙箱；不安装、不联网、不补造业务结果。
- Workpack 可声明 `effects: {"required":["output/report.json"], "allowed":["output/report.json"],
  "must_preserve":["input/data.json"]}`。精确文件名，不是 glob。required 包含全部产物且是
  allowed 子集；allowed 必须在批准写域，不能与 must_preserve 重叠。

required 表示最终应存在的文件，不强制唯一源码或无意义重写。文件内容和持久业务状态
仍由独立只读 checker 根据公开合同验证；生产者 DTO 自洽、退出 0 或文件存在不能代替语义验收。
must_preserve 在派发前必须为已有文件。宿主观察本任务全部批准写根和指名保留文件，
比较文件内容/模式及目录存在性；不承诺目录元数据、短暂写后还原、外部服务或全机副作用证明。
symlink/特殊对象或无法完整观察时停止，不把不可观察解释为 PASS。

新字段沿用原提案/批准绑定；重规划不能删改 effects/environment。带契约的 split/merge
必须完整保持原契约，否则报告批准边界冲突。旧 1.0 无契约时 effects=NOT_DECLARED，
不能声称有新版效果证据。当前扩展不提供通用服务探测或外部状态事务。

## 语义、输入与修复连续性

搭建文档明确分开现状事实、目标行为、持续约束、用户待决事项。现状不机械转成 Case；
目标义务进入 Atom/Case；复合条款可拆分但原意不丢。不能按标题、关键词、来源号分 owner。
组件建设验证与最终运行验证分别归属，不能要求上游契约先证明下游真实提交/渲染，也不能
借修正依赖删掉最终行为义务。完整来源和全局约束保持可读。

运行时 `accepted_inputs` 来自当前 accepted 投影，含 producer、产物、proposal、attempt、
acceptance event 和文件身份。未验收资料不会混入；同路径 replacement 覆盖后的旧版本保留
接受证据，但 `current_bytes_available=false`，不提供伪造的旧版本路径。正常/恢复链均检查。

`repair_history` 给出相关失败、Case、效果、声明的执行方法及原 attempt/command 引用；长输出只提供摘要，完整附件不删。
声明方法不是模型内部推理记录；失败 attempt 的已观察产物仍明确标为未验收。
相同标签不机械禁试，但应基于新证据/不同假设修复；不得无意义重复上一动作。当前预算不退款。
该修复方法约束目前由显式历史和指导支持；控制器不推测模型的内部假设，尚不能宣称已机械
阻止全部无效重试。设施失败的自动停止已回归，真实模型是否避免同因重复留待 G5R/G5E 验证。
语义检查器仍独立；目标不能修改 Foundry 或 checker。文件越约且无法归因时 HOLD，不自动恢复
用户内容。原事件库是唯一权威，没有新 Hash 链、恢复引擎或通过自报覆盖失败的入口。

`read-build` 展示 phase、预算消耗/剩余、owner、evidence、minimum_return_path，进行中命令提供
耗时、最新输出时间及字节数。它们是诊断，不是“仍在成功推进”的推断。
开发示例 `devtools/release_acceptance/observation_window.py` 用 ready→subscribe→trigger→bounded
collect，避免固定 sleep 漏掉短窗口；项目适配器必须提供非阻塞 trigger 和真实订阅/取消语义。

## 效果如何评估

回归先证明确定性保证：前置错误执行前拒绝、设施失败不派发实现、保护文件误删拒收、
检查后的漂移不接受、恢复不重跑。它们不证明模型一次生成成功或效率提升。

`quality_report.factorial_summary` 分原/新版 Foundry × 原/澄清文档四组，保留每任务、首轮/修复
历史、原始证据及条件；原义务和独立 checker 不变。未知 token/成本保留 null，缺组 NOT_RUN，
对同一任务跨组核对原业务合同、输入、工具/权限/预算；条件或任务集合不一致则不可比。
不同任务可以有不同合同/输入；澄清文档不能改变被比较的原业务义务。
报告本身不认证证据，也不自动宣称统计收益。
真实评测要补充精确源码提交/包、模型/服务、工具、目录、预算和有效期批准；本轮不代造批准。

### 回归样例与保留任务分离

来源是已存档的四篇论文研读与 AICut 归因，不是本轮重新访问 AICut 运行库。
“规范归属错位”是项目合同问题，Foundry 加声明关系检查；“设施故障”是运行准备问题；
“当前输入/误删/恢复”是控制器公共保证。对历史现场没有重建证据的项仅作为设计动机。

| 开发回归（确定性临时环境） | 正常对照 / 错误输入 | 当前证据 |
|---|---|---|
| Case 前置依赖下游 | 本地输出或合法前驱 / 下游与隐式输入 | `test_build_plan` 两种合法归属均通过；1.1 是版本化能力新增 |
| 设施不足 | 同 Python 的 stdlib / 缺模块 | `test_build_runtime` 预检 PASS 或无实施 BLOCKED；不冒称历史业务 RED |
| 输入串用 | 当前 accepted 版本 / 变化与被覆盖旧版 | `test_build_runtime` 当前输入绑定、replacement、分支失效回归 |
| 无关文件误删 | 仅允许输出 / 删除保护文件、额外文件 | `test_build_runtime` 结果正确但效果违约仍拒收 |
| 修复、恢复和短窗口 | 原 attempt 证据 / 观察中断与漂移 | `test_process_observation`、`test_build_runtime`、事件窗口适配器回归 |

保留任务设计单独保存在开发目录 `devtools/release_acceptance/UPGRADE_HELD_OUT.md`，
不进入 source gate 或默认包。它们是 NOT_RUN，不是独立盲测证明；具体数据待固定被测版本
后确定。小样本只能报告样本内结果，失败、设施阻断和未运行分别保留。

## AICut 采用路径（未执行）

1. 保留现有 Harness、旧报告和接受记录。单独核对正在使用的版本，不能因升级 Foundry 自动替换。
2. 对契约模块的 Case 分离建设就绪与真实提交/渲染义务，标明实际所需前驱，保留最终验收。
3. 为已有代码/配置/用户资料列精确保留义务；输入只引用当前被接受的对应产物，修复输出使用
   当前 attempt 独立目录，不让闭包携带旧路径覆盖旧截图/报告。
4. 先声明实际 Python/构建依赖、ready 订阅和测试接口，再确认必要运行范围。CORS、UI 状态、
   音轨/渲染等业务实现仍归 AICut；不能宣称本次 Foundry 源码修复已修好这些功能。
5. 经单独授权后修订项目合同/重新生成，再用原业务义务回归；完整运行验证与本地文件检查分报。

## 当前验证记录

最终公开 source gate：**267/267 PASS，零跳过、零失败、零错误**。
`tools/check_release_source.py` 同时覆盖临时开发包迁移、依赖闭包、启动和 Skill 检查；
其中新增 Plan 1.1 临时迁移测试实际走预检、效果检查与恢复，不只检查 ZIP 文件存在。
定向最终变更回归为 124/124 PASS；收益报告随后增加的跨任务对照回归也已包含在最终 source gate。

兼容快照回归发现 986 项，排除以下 2 项修改后 Python 执行用例后选择 984 项：
**964 PASS、20 项原生沙箱 opt-in 跳过、零失败、零错误**，用时 904.889 秒。
这是按“不做动态攻防”范围执行的离线兼容回归，不是 986 项全通过，也不是原生运行验收。

- `test_release_closure_candidate.Epoch2CandidateTests.test_hash_consistent_authority_adapter_weakening_is_rejected`
- `test_release_closure_candidate.Epoch2CandidateTests.test_hash_consistent_closure_runtime_weakening_is_rejected`

20 个跳过项的完整 selector 和原因保留在兼容日志末尾；未配置或打开原生沙箱 opt-in，
未以跳过代替必要公共 Gate。兼容 suite 启动后补入的 Plan 1.1 迁移用例以及后续报告修正，
已由最终 267 项 source gate 重新覆盖；分批结果不冒称为同一次最终树全量运行。
静态规范核验另行 PASS（101 文件），最终打包只读预检 PASS（37 文件，保留评测不入包）。
不把 source gate 的零跳过数字用于兼容层。报告名为 `foundry-upgrade-source-final-v5-20261010.json`，
兼容日志名为 `foundry-upgrade-compatibility-20261010.log`，均在本次本机临时目录；不是发行资产。

默认 Python 缺 jsonschema 的失败已保留；随后复用已有测试 venv（Python 3.13.3），未安装依赖。
开发中修正了新说明文件漏入旧便携清单、迁移测试错误引用夹具文件名，以及收益报告跨任务
错误比较输入的问题；最终回归未删断言来放行。这些是本轮增量修正，不冒称重现了 AICut 全部历史故障。
固定提交评测包、真实模型、收益对比、AICut 变更、Git 提交/推送和发版均未执行。
本次结论是 **G5S 源码升级已验证**，不是整个计划已闭合：G5R 实用、G5E 收益仍为 NOT_RUN；
后续需确定正式评测源码/包、模型服务、工具、目录与预算，不能继续沿用旧版本的实用证据。

### 可复跑的关键 selector

在测试依赖齐备的环境，用 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -B -m unittest <selector>`。
完整公共 Gate 为 `python -B tools/check_release_source.py --report <新的临时JSON路径>`。
以下为精确 selector；其余正常对照、已有预算/恢复/分支/只读检查继续由原 suite 覆盖。

| 工作包 | 精确回归 selector |
|---|---|
| WP03 / 错误前置 | `test_build_plan.BuildPlanTests.test_case_cannot_require_a_downstream_artifact_at_an_upstream_stage` |
| WP03 / 合法前驱与隐式输入 | `test_build_plan.BuildPlanTests.test_consumer_case_accepts_declared_predecessor_but_not_implicit_input` |
| WP04 / 设施不足不派发 | `test_build_runtime.BuildRuntimeTests.test_environment_preflight_missing_module_never_dispatches_implementation` |
| WP04 / 正常路线 | `test_build_runtime.BuildRuntimeTests.test_quality_contract_normal_route_uses_readonly_preflight_and_host_effects` |
| WP05 / 输出是诊断不是验收 | `test_process_observation.ProcessObservationTests.test_progress_is_visible_before_completion_and_never_acceptance` |
| WP05 / 短窗口 | `test_release_acceptance_adapters.ReleaseAcceptanceAdapterTests.test_event_window_subscribes_before_short_lived_action` |
| WP06 / 接受事件与当前输入 | `test_build_runtime.BuildRuntimeTests.test_downstream_gets_current_accepted_input_and_acceptance_event` |
| WP06 / 同路径版本修复 | `test_build_runtime.BuildRuntimeTests.test_in_place_replacement_can_repair_without_reusing_old_version` |
| WP07–08 / 误删拒收 | `test_build_runtime.BuildRuntimeTests.test_effect_contract_keeps_protected_file_even_when_checkers_pass` |
| WP08 / 检查后漂移 | `test_build_runtime.BuildRuntimeTests.test_recovery_cannot_accept_postcheck_preserved_file_drift` |
| WP09 / 失败历史进入修复上下文 | `test_build_runtime.BuildRuntimeTests.test_actual_failed_checks_repair_then_accept_before_next_task` |
| WP10 / 恢复不重做 | `test_build_runtime.BuildRuntimeTests.test_effect_baseline_is_reused_after_controller_interruption` |
| WP10 / 契约不能被重规划删去 | `test_build_runtime.BuildRuntimeTests.test_pending_replan_cannot_remove_effect_or_environment_contract` |
| WP11 / 临时迁移运行 | `test_generic_distribution.GenericDistributionTests.test_relocated_plan_11_preflight_effects_and_resume` |
| WP13 / 不伪造收益或可比性 | `test_release_acceptance_adapters.ReleaseAcceptanceAdapterTests.test_factorial_report_keeps_unrun_and_unknown_costs_unknown` |
