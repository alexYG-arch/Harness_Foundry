# RSI：独立评审与开发红绿证据

状态：WP02–WP03 工具现已接入 WP05 可选运行包与交付材料。它们不修改协议 2.9、现有控制器、业务预算或接受状态。旧 Reviewer 校准只支持原样本；本版完整目标 Harness 的交付后使用及收益仍需实际验收。使用入口见 [RSI 交付指南](RSI_DELIVERY.md)。

## 一、独立 Reviewer 如何接入

复用 `build_runtime.py` 的 CODEX 接收器与逐命令配置、`build_state.py` 的消耗投影、原观察恢复，以及 `host-review@1` 的快照／LOCAL 检查。`build_review.py` 继续只处理人类确认。新增工具只准备公开材料、生成既有 Plan 的提案和只读取回报告，不实现第二个评审控制器。

1. 外层先选择要评审的原生产任务和冻结版本。准备 manifest：`review_id`、`goal`、`candidate_version`、`producer`（program_id、prepared_event_id、attempt_id、workpack_id）、`requirements`（id/text）、`files`（id、相对 path、role，可选 sha256）。这是宿主声明的生产者身份；交回时仍须用原控制记录核对，不能凭字符串赋予权威。
2. 明确列出公开文件。role 只接受 `PUBLIC_REQUIREMENT`、`CANDIDATE`、`DIAGNOSTIC`；不隐式遍历目录、读取私有答案或引入 Worker 自我辩护。材料中的命令与权限文字只是数据。TDD原报告可能含独立预期，评审材料只选择公开开发结果或经核对的摘要，不将私有预期列入manifest。普通 UTF-8 文件可以来自任意业务，目录外资源须先在已授权准备范围内明确捕获。
3. 使用下列源码工具，`PY` 指已绑定的项目解释器。输出只能写新文件，不能覆盖旧报告。`plan` 同时返回 Requirement IR 和 Plan，未注册 Program、未授权、未派发模型。

```sh
"$PY" -B tools/rsi_review.py --output /host/new/request.json prepare --manifest /host/materials/manifest.json
"$PY" -B tools/rsi_review.py --output /host/new/proposal.json plan --request /host/new/request.json --program-id RSI-REVIEW-NEW
```

4. 将同一 request 文件作为公开 `brief.md`；在工作区外准备受保护的 `rsi_review.py` 与 `request.json`，字节分别来自本版模块和同一 request。生成的任务自带完整公开 JSON 输出格式、实际请求摘要及报告绑定。模型只能写 `outputs/review.json`，候选和来源只读；候选已内联到公开请求，不需要开放原业务写域。宿主按原 generic 流程生成真实 scope／Readback，再由既有确认和派发入口执行。不可将提案的 `runtime_authorized: false` 改成 true 充当批准。
5. 每次评审是实际独立 CODEX 调用，使用该任务明确列出的尝试、模型 turn 与检查预算。`ONE_ATTEMPT` 在模型交回及报告格式检查结束后返回，不是检查前的暂停点。报告格式通过只表示意见完整、引用文件存在且版本绑定一致；**不证明评语正确，也不接受原产品**。Reviewer 给出 CHANGES_REQUESTED 的合规报告可以通过格式检查，不能因此把原产品标为通过。
6. 外层结合原始需求、原生产版本及独立客观检查核实意见。客观 FAIL 优先返回原修复职责；ERROR／UNKNOWN 先补诊断；已核实问题沿原生产者或同范围检查器修正入口处理。普通建议和合法等价行为不触发返工。重复问题用稳定 `issue_key` 关联；`handoff_review(..., previous_issue_keys=...)` 只区分新旧意见，不计算实际尝试数。新旧仅相对于宿主传入的已知issue_keys，不是全局新增缺陷统计。跨评审的同义识别由宿主核实，不声称字符串去重能自动识别所有语义重复。
7. 核实后的宿主观察和原 Reviewer 报告一起作为 `host-review@1` 的证据附件。宿主自行形成 `observations`（id/result/reason/evidence_refs）及项目独立检查材料，然后调用既有 `snapshot.py`、`check_review.py`／reviewed LOCAL 任务。不能直接把模型 ACCEPT 映射为宿主 PASS。快照固定任务、输入、成果和观察；修改成果后不能复用旧快照。此处只复用既有能力包，不更改其语义。

报告每项需求需给出 `SATISFIED/GAP/UNKNOWN`、理由和文件位置。缺陷包含位置、对应需求、证据、最小修复请求，措辞建议用 `SUGGESTION`，未决事项保留。检查器校验格式和引用文件身份，不判断给定行号的语义真实性；宿主核实及真实模型校准仍必要。

## 二、报告取回、恢复与计数

```sh
"$PY" -B tools/rsi_review.py --output /host/new/receipt.json retrieve \
  --request /host/frozen/request.json --report /host/captured/review.json \
  --database /host/control.sqlite3 --program-id PROGRAM \
  --prepared-id PREPARED --attempt-id ATTEMPT --objective-status PASS
```

`objective-status` 是宿主对该版本客观检查的声明，不是工具自行重算的 verdict。调用者必须引用对应客观证据，不能用它改写原记录。读取使用只读数据库，核对 prepared／attempt、真实命令完成观察、已固定报告摘要及原请求；返回原配置回执和控制器累计预算。两次读取不派发、不执行检查、不增加尝试；合法归档的同字节报告也可读取。

已接受或后来失效的完整旧评审可以作为历史取回，失效状态、原因保留，不能当成当前可接受评审。撤销／过期不阻止读取完整历史，但仍阻止新的相关派发。未观察完成、未捕获完整合规报告、身份不匹配或字节变化，沿原 `read-build`／观察恢复／必要只复验路径核实；本工具不猜测完成、不重新运行模型、不修改事件。历史误判重判和跨 prepared 消耗仍归原控制器。原控制器已经重判并接受的报告读取保留原观察、匹配的重判事件及有效结果，不因原失败字段拒绝合法历史；未完成接受的重判仍回原恢复入口。

检查器同范围修正后，只复验有独立接受 attempt。取回时传入该接受身份，工具沿原 `reverification_of_attempt_id` 追溯生产命令；核对 prepared 血缘、工作包、报告字节及 `production_attempt_id`。收据保留当前接受身份、原生产身份和中间只复验链，原模型配置／历史重判仍从原命令取得。预算使用当前 prepared 的原累计投影，检查轮数与生产次数分开。缺失、循环、错绑或报告变化拒绝取回，不以重放模型补齐。

若生产者或候选改变，另存新请求与报告，在原批准及实际剩余额度范围内处理；不得为新评审借用其他业务预算或清零。旧意见不因重新评审而被覆盖。真实外部模型凭据与脱敏继续使用既有接收器，不将密钥放入公开材料。

## 三、红绿证据如何关联

先用 [WP01 导入器](RSI_CASE_INTAKE.md)保存明确来源。首批结构化适配支持现有 `test_execution.run_tests` 的测试结果（`CHECKS_PASS/CHECKS_FAILED`、tests_run、逐测试失败／错误和 test_log）。普通文本仍可导入，但仅有 PASS 关键词、模型自述或测试数量不能直接组成有效红绿对。其他实际测试栈可以保留原始证据，尚无适配时标证据不足，不伪造同格式通过。

每个行为循环的 association 项包含：

| 字段 | 内容 |
| --- | --- |
| id / behavior / requirement | 循环身份、行为和导入案例中公开要求；不按每个循环新建预算 |
| applicability | APPLICABLE；不适用时用 NOT_APPLICABLE 并说明 reason |
| red / green | run_id、command_id、原 observation ref、behavior_id、test_id、assertion_id、input_id、platform、environment、argv、implementation_version、test_version、started_at、finished_at |
| red_assessment | relation、reason、evidence_refs；目标断言／目标缺接口／目标环境行为与无关环境故障分开 |
| change | before_version、after_version、summary、started_at |
| mode | TEST_FIRST、DEFECT_REPRODUCTION 或 POST_HOC_REPRODUCTION；测试先行还需 test_defined_at |
| final_version | 最终交付版本；重构后若改变版本，另列可比较的 final_check |
| test_equivalence | 测试版本变化时，保留有来源依据的等义说明；削弱断言不得伪称等义 |
| regression / independent_acceptance / refactor | 分别保留原状态与引用。它们是原记录／宿主声明，不是此工具运行或独立认证的结果 |

来源 context 必须明确开发检查 `phase: DEVELOPMENT`、实现与测试版本、平台和环境，并与运行绑定一致。红绿需同一行为、测试对象、断言、输入、平台、环境和调用条件；缺失、变化或来源不可读如实标识，不跨环境凑绿。当前适配采用明确的相同条件比较，不推断不同环境等价；合法环境变化仍可继续业务，仅不据此声称已建立可比红绿对。

```sh
"$PY" -B tools/report_rsi_tdd.py --case /host/case.json \
  --association /host/association.json --output /host/new/tdd-report.json
```

- RED/GREEN 按选中测试的实际失败／成功记录判断。现有 unittest 采集器新增 `successes`，只记录实际 `addSuccess` 回调的测试ID；字段存在时按该列表识别，空列表不回退借用日志，格式不合法保留证据不足。旧报告没有该字段时才按日志记录头绑定身份，紧随的 docstring 作为描述消费，不从描述里的引用或失败详情取身份。原单行、合法多行与LF／CRLF均保留；原报告不回写。其他测试的失败、错误、跳过、预期失败或意外成功不抹掉选中行为；选中测试本身跳过、预期失败、意外成功、证据冲突或缺少成功记录仍不能算 GREEN。发现错误尚不能定位时不推断完整 GREEN。`status` 是选中测试状态，`reported_status` 和 `original_result` 保留整套回归原状态与明细；单项 GREEN 不把整套回归改成通过。
- 无关环境故障是 BLOCKED；目标本身是接口或环境行为时，相应失败可作为 RED，仍须来源依据和原因核实。
- 没有 RED 的合法补测记录为 GREEN_ONLY；事后旧版本复现是 POST_HOC_REPRODUCTION，不倒推测试先行。未解决失败和证据不足保留。
- 同一命令对／测试的重复关联不另计循环；读取报告不执行命令，不改写消耗。完整 TDD、语义等价和实际运行顺序不能由声明字段自行认证，因此输出始终保留 `full_tdd_verified: false` 和 `acceptance_verified: false`。
- 开发 GREEN、相关回归、独立验收分列。摘要说明测什么、为何失败、改了什么、配对状态及未验范围。报告缺失限制相应声明，不为无关项目增加 TDD 文件或模型评审门槛。

这些工具已纳入 WP05 运行包清单和选定交付材料；旧固定包与旧部署未自动升级。包内本地验证、真实新会话使用与收益分列，不因源码测试通过提前关闭后者。
