# RSI WP08 最终集成证据归并记录

> 分支公开说明：本页保留计划、实现与验收结论摘要，不包含原始运行证据、控制数据库或实际 Readback。本机原件和累计记录独立保留；历史“未推送”描述对应当时状态，本次仅推送分支，不合并 main、不发布。

日期：2026-10-23。**WP08／G08 原定所选集成范围完成**：已逐项核对当前实现、最终完整回归、固定包及 G02／G05 实际证据。此结论不表示实际项目已采用新机制、收益已证实或整个 RSI 已完成。WP09 收益与 WP10 最终交付说明仍沿原 Workpack 后续处理。

## 本轮动作与复用依据

本轮使用项目 `.venv` 执行只读证据核对，归并原 G08 条件，不新增功能、控制器、门禁或验收分母。未发现需要修复的实现缺口，也没有需要新增运行才能覆盖的 G08 所选条件，因此没有重跑完整回归、源码门禁、已接受模型、检查或业务命令。归并脚本只读源码、归档、日志和原收据；没有连接或编辑控制数据库。

- 对照上轮测试前清单，**406 个受测源码、测试和工具等文件字节未变**。复用最后一轮完整回归 **2173 项：2116 通过、57 跳过、0 失败／错误**（测试日志约1115.484秒），各执行退出记录为0。
- 同版源码门禁 **865 项通过**、规范 **101 文件**和 Skill **8 引用**通过。定向134项属于重叠集合，不额外相加。
- 重算现有打包清单与组装字节，**224 文件固定候选与当前选定源码一致**。原包保留，本轮不重新打包；8条包内隔离入口验证复用原记录。这些是工程检查，不称本轮新模型验收。
- 原221文件 G05 宿主包与34文件已接受 Harness 保持原摘要。当前224文件包相比旧宿主包：217原样、3新增、4变更、0删除。变更限包清单、两份指南及可选交付列表；Wiki／Reviewer／TDD、采集器及执行核心不变。新采用关联入口及新交付列表由最终工程和隔离入口测试覆盖，旧真实使用不延伸成其真实采用证明。

固定候选 SHA-256：`2de1653d4b8d1e8b63ed2cae9f4c57b68ae6be8e0814711231f15c967cbd2934`。
原包：`本地保留位置`。
基线提交仍为 `da7f77facbb93062478617782c8da2074eeb037b` 加本地 RSI 工作区实现；不能把该提交 SHA 单独当作本候选的完整版本身份。

## 原 G08 覆盖表

下表只是原标准的展示分组，不新增 Gate、用例或分母。精确测试方法、源码行和原日志行见本轮 `coverage.json`；原日志位于 WP06/WP07 证据目录的 `full-regression-v1.log`。

| 原标准 | 已有证据与核对结果 |
| --- | --- |
| 可比较红绿、原证据及独立验收待运行 | `test_comparable_pair_keeps_all_originals_and_no_acceptance_or_budget`、`test_developer_and_independent_evidence_are_not_mixed` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| 目标接口／启动错误与无关环境区分 | `test_unrelated_environment_is_not_red_but_target_environment_can_be` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| 缺RED、合法补测、不适用、选中测试身份 | `test_legal_green_only_and_not_applicable`、`test_no_selected_test_no_red_pair` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| 跨平台与条件变更、断言放宽及等义修改 | `test_different_platform_or_environment_kept_separate`、`test_test_change_needs_equivalence_and_weakening_is_not_paired` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| 先行与事后复现、最终版本变更 | `test_posthoc_reproduction_not_original_test_first`、`test_final_refactor_requires_final_version_check` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| 原报告恢复及重复关联不计次 | `test_restored_report_rechecks_binding_without_discarding_old_case`、`test_repeated_pair_and_repeated_read_do_not_count_twice` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| Reviewer公开材料、误报与客观失败边界 | `test_explicit_public_inputs_do_not_copy_private_or_worker_defense`、`test_legal_equivalent_and_wording_suggestion_not_rejected` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| Reviewer计数、完整报告取回及只复验关联 | `test_existing_controller_counts_review_and_reads_twice_without_replay`、`test_accepted_recorded_reassessment_can_be_read_without_stream_replay` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| 当前交付闭包、隔离CLI、所选工具及空选择 | `test_relocated_delivery_has_exact_dependencies_and_no_authority`、`test_empty_selection_does_not_block_or_execute` 等；原日志逐项为 ok，测试实现与已测版本一致。 |
| 候选与旧GREEN、维护归属及部署边界 | `test_final_source_change_retains_old_green_without_certifying_new_file`、`test_fail_skip_unknown_remain_original_not_upgraded_to_pass` 等；原日志逐项为 ok，测试实现与已测版本一致。 |

另行归并普通流程的原回归记录：`test_build_review`14项、`test_build_runtime`116项、`test_build_runtime_context`11项、`test_build_correction`38项、`test_build_reconciliation`25项及组件升级3项均通过。它们均属于上述2173项，不再加总。覆盖同范围修正、跨 prepared 消耗、撤销／过期、观察恢复、接受复用及文件级续行；未修改其实现。

Reviewer 的只复验恢复、未知／缺观察拒错、撤销后原报告读取由现有工程用例覆盖；不把合成接收器或工程夹具称为真实模型故障注入。

## 实际模型与交付后使用的适用范围

**G02 五项校准复用：**原实际 Reviewer 找到需求遗漏、接受合法等价与非阻断措辞、保留证据不足、识别无关 RED 和削弱断言。原报告与两次收据摘要一致，原客观 FAIL 和不接受产品状态保留。核对其校准记录及原报告绑定，保留当时1次生产／1个模型turn、1次合同检查、1次宿主检查，不重新调用。该记录只证明原五项判断；其后取回代码变化由当前工程回归覆盖，不声称修后发生过新的真实模型只复验。

**G05 所选真实闭环复用：**重新核对原 USE／REVIEW 完整原始流、实际命令完成事件、两次原收据、最终接受产物摘要以及宿主快照与报告。USE与REVIEW分别15／5条完成工具命令，模型完整结束事件均存在；日志预览截断未丢完整流。独立检查按公开范围通过，Reviewer 原 UNKNOWN 和四项缺口保留，宿主已从原证据核实，没有将格式通过冒充语义结论。

原实际路径为新目录／新模型会话／新整数输入，实际调用交付 Wiki 查询与记录入口、目标 CLI、案例导入及 TDD 报告；**Wiki 无命中＋空采用、TDD 不适用**。G05合同允许无命中继续，不能为了证明收益强迫命中或制造 RED。源码及移位交付测试覆盖合法匹配、拒错、真实本地红绿；它们不抵匹配知识在真实任务中的收益验收。所选目标不依赖本轮新增的采用关联入口，因此无需升级或重跑已接受目标。

真实证据分列：

- G02：`本地保留位置`。
- G05：`本地保留位置`、`use/actual-tool-audit-r2.json`、`review/receipt-1.json`及`receipt-2.json`、`host-review/result-v2.json`。
- 具体执行与历史误报保留于[G05执行记录](FOUNDRY_RSI_WP05_G05_USE_REVIEW_EXECUTION_2026_10_23.md)及[WP02/03实施记录](FOUNDRY_RSI_WP02_WP03_IMPLEMENTATION_2026_10_23.md)。

## 预算、恢复与清理

本轮新增生产、模型turn、业务调用和独立业务检查均为0。源码证据核对不是新的生产尝试；不在旧预算上记取回次数，不通过另存归并文件清零。

| 原批次 | 保留原消耗 | 本轮新增 |
| --- | --- | --- |
| G02校准 | 生产1／2、模型1；合同检查1、宿主检查1 | 0 |
| G05搭建 | 生产1／2、模型1、独立检查累计4 | 0 |
| G05 USE | 生产1／2、模型1／2、检查1／2 | 0 |
| G05 REVIEW | 生产1／2、模型1／2、检查1／2 | 0 |
| G05 HOST | 2／2；首轮快照准备错误、第二轮通过 | 0 |

剩余额度是历史计数，不延长已批准有效期，不授权另一个用途。原失败、UNKNOWN和受影响前记录保留。原USE的scratch／report-staging清理、空资源根保留按原合同解释；REVIEW未声明服务资源，报告继续保留。本轮不启动服务或产品子进程，不执行新清理，不改旧目录或数据库。

## 57项跳过及仍未验范围

57项名称及原因与WP05最终日志逐项一致：35项native receiver opt-in、11项真实Codex sandbox opt-in、8项real local sandbox、2项pytest解释器及1项离线OS sandbox。均不计通过；G02/G05的实际调用单列，只覆盖其明确版本、工具和断言，不抵这57项的全部原生矩阵。

尚未证实：匹配知识被真实采用后的效果、当前新增采用关联工具在真实目标中的采用、完整TDD语义真实性、一般Reviewer准确率、真实候选机制收益、跨设备效果、生产部署与连续递归收益。WP09需按原计划另行准备并获批具体运行范围；本轮不预设收益，也不自动增加样本。WP10最终说明未在本轮执行。

**完成口径：**WP00–WP08 的适用源码和 G08 所选集成条件完成，可称原计划限定机制范围完成；不称全部RSI100%、全部原生验收通过或项目已部署。原R3和既有分母不变，协议2.9，不扩展G1/G2、不增加通用限制、不推送、不发布。

## 本轮归档

证据目录：`本地保留位置`。`reconciliation.json`保存版本、复用范围及预算；`coverage.json`与`ordinary-build-coverage.json`保存原标准到原测试日志的对应；`evidence-identities.json`保存所读旧证据摘要；`skipped-tests.json`保留全部跳过。核对脚本与只读执行说明另存，旧证据没有覆盖。

归并过程中，日志索引脚本初次把一条夹有诊断JSON、下一行才输出`ok`的合法记录视为不完整；调整只读索引后核对通过。此为本轮归并准备错误，不是产品回归失败，未重跑原测试、不增加生产或模型消耗。
