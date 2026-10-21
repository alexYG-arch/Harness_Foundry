# 三组业务的普通文件交接约定

这是 R3 选定示例的文件约定，不是 Generic 协议或新执行器。V1/V2 使用各组原始输入、任务和选定工作流；独立 `expected.json`、检查器及宿主审阅材料不发给成果生成者。下面的 JSON 字段使已有成果可读取；文字、布局和实现仍允许不同正确表达。所有本轮运行仍为 NOT_RUN；测试中的合成输出与合成审阅记录只测试判定路径。

## 产出及自动检查

各组清单中的文件名不变。JSON 可包含其他解释字段，但不能遗漏下列字段。自动检查不是整组业务接受，不能证明模型实际加载工作流、实际计算执行、视觉质量或引用支持性。

### PRD＋设计

`prd.md`、`prototype.html`、`design-notes.md` 必须非空。`traceability.json`：

```json
{
  "requirements": [
    {"id": "R01", "prd_section": "PRD 中真实章节定位", "prototype_refs": ["原型中的真实页面或控件定位"]}
  ],
  "states": ["empty", "offline_draft", "submitting", "network_error", "capacity_conflict", "confirmed"],
  "view_widths": [375, 1280],
  "customization": {"这里填": "inputs/user-customization.json 的完整原值"}
}
```

`requirements` 必须各出现一次 R01–R08；上面的 R01 只演示一行。定位必须指向实际成果，不能把示例占位文字直接提交。自动检查只核对定位字段存在，独立宿主检查定位内容与原始需求真正对应。

V2 的 `state-transitions.json` 为 `{"transitions": [...]}`，每行包含 `from`、`action`、`condition`、`to` 字符串及 `preserves_contact_draft`、`reservation_created` 布尔值。须包含以下相邻转换，动作和条件按实现填写：

- `offline_draft → pending_user_retry → submitting → confirmed`
- `submitting → capacity_conflict → selection`

恢复和重试的未确认转换保留联系人草稿；成功进入 `confirmed` 后允许清除本地草稿，本次确认凭证中的联系人展示仍须满足原始需求。只有到 `confirmed` 的转换可以声明已产生预约。文件的转换声明不证明浏览器行为；宿主仍需实际操作并判断 R01–R08、两个宽度、长文案、键盘及错误关联。

### 数据计算推理

`normalized-orders.csv` 只列按原口径筛出的有效已付款记录，每个 `event_id` 一行，列为 `event_id,revision,local_time,channel,amount_yuan`。时区转换后用带目标偏移的 ISO 时间，按实际时刻与偏移核对，允许秒与零微秒等价表示；无时区、未转换到目标偏移或不同时刻均不合格。未知金额保留空单元格，不写 0。

`metrics.json` 包含以下键：`eligible_paid_count`、`known_amount_count`、`unknown_amount_count`、`known_revenue_yuan`、`amount_coverage`、`known_amount_mean_exact_yuan`、`known_amount_mean_display_yuan`、`complete_revenue_yuan`、`complete_mean_yuan`、`growth_rate`；最后三个在当前输入下为 JSON `null`。金额和比例可用十进制字符串或 JSON 数字；推荐字符串保留显示精度。另带 `definition`（完整原指标口径）及 `customization`（完整原用户参数），便于核对保留情况。

V2 在 `metrics.json` 增加 `groups`，以渠道名为键，每组以 `eligible_paid_count`、`known_amount_count`、`known_revenue_yuan` 分别表示有效数、已知金额数及已知小计。`sensitivity.json` 包含 `cap_yuan`、`assumption`、`revenue_min_yuan`、`revenue_max_yuan`、`all_paid_mean_min_yuan`、`all_paid_mean_max_yuan` 和 `is_actual_complete_revenue:false`。未知金额仍未知，区间是用户参数下的条件情景；`analysis.md` 说明公式、分母、未知和推断限制。

检查器独立读取原 CSV，用 Decimal、修订规则、时区、过滤和单位复算；不执行或导入生成方脚本，不从生成方结果推导答案。它核对数值和声明口径；“实际调用了计算工具”及文字是否越界由独立宿主对真实执行记录和解释判断。

### 固定材料市场调研

`source-register.json` 为 `{"synthetic":true,"sources":[...]}`。来源行保留原 `inputs/sources.json` 的 `source_id`、`filename`、`published`、`kind`、`paragraph_ids`。`claims.json` 包含：

- `scope`：完整原 `inputs/research-scope.json`。
- `observations`：M01/M02 各一行，包含 `id`、`statement`、`numerator`、`denominator`、`ratio`、`citations`。引用格式为 `S01:P1`，保留必要的样本与限制段落。
- `price_conflict`：`citations` 保留双方来源，`values_yuan` 保留两条价格，`resolution` 为 `"unknown"`。
- `unsupported_claims`：列 M04、M05、M06，表示这些推断不被资料支持。

`research.md` 用自然语言回答原任务；V2 增加 `evidence-gaps.md`。编号/比例正确不保证文字正确，宿主仍按原文判断每个结论、冲突、建议、日期和未知，尤其不能只读 `unsupported_claims` 标志就认定全文没有越界。

### 实时检索分支

该分支单独用 `market-live` 检查，只产出 `live-source-register.json`、`live-research.md`；固定包的完成不能代替它。宿主按 `live-task.md` 实际调用 `web__run` 的 `search_query` 和 `open`，保留实际工具结果。CODEX 子任务不会继承这些工具。

`live-source-register.json` 为 `{"as_of":"执行当天 YYYY-MM-DD","sources":[两条不同产品记录]}`。每条包含：

- `product`、`query`、`url`（实际打开的原始网页）、`title`、`search_tool_ref`、`open_tool_ref`。
- `retrieved_at`：带时区的本次 ISO 时间；`published_at`、`updated_at`：可见日期或 `null`。
- `currency`、`billing_period`、`tax`、`region`：原文条件或 `null`，不猜测未说明内容。
- `claims`：`feature`、`price`、`trial` 三项。已知项形状为 `{"value":"原文事实","excerpt":"短支持片段","location":"原文位置"}`；价格或试用条件未说明时为 `{"value":null,"unknown_reason":"实际未找到的内容及范围"}`。功能须有原文依据。

自动检查只能验证记录形状、`as_of` 日期及带时区的 `retrieved_at` 时间格式。独立宿主在 `claim-support-and-dates` 中结合实际执行时区与工具记录核对本次执行日；不同 UTC 偏移下的日历日期可以不同，后续 LOCAL 复核日也不替代原执行日。两个产品是否真实、网页是否官方、工具调用是否实际发生及片段是否支持结论，都由独立宿主打开原始来源判断。URL 可解析、JSON 完整或一个自填 tool_ref 均不足以证明实际检索。

## 实际宿主交接顺序

1. CODEX 任务读取选定工作流及原始输入、产出声明文件。自动检查接受的合同只限文件/数值准备，不宣称业务整体接受。实时分支由约定宿主实际检索并交付文件，不能让 CODEX 编造检索结果。
2. 整次 attempt 返回后，宿主固定真实成果及执行记录；PRD 原型按已声明工具渲染/操作，研究按真实来源审阅，数据按运行记录和解释审阅。没有使用 `ONE_ATTEMPT` 在实施与验证之间插入宿主的假设。
3. 独立审阅者在实现写域之外保存下述 `host-evidence/`。它可以是宿主的独立检查流程，不要求每项新增一次用户批准。不得由成果生成者自填一份 PASS 后充当独立检查。
4. 后续 LOCAL 检查使用新准备的受保护副本，读取成果与证据；无需重新执行 CODEX 生产者。普通文件复制/应用只建立当前检查输入，是否正式接受仍由现有控制器决定。升级产生的新成果须重新核对，不能把旧截图、检索或运行报告贴到新结果上。

```text
host-evidence/
  review.json
  workflow.md           # 实际被审工作流的原始字节
  reviewed-output/      # 受审成果的原始字节，文件名对应组清单
  evidence/             # 真实截图、交互记录、调用/计算记录、来源摘录等
```

`review.json` 的普通字段如下；占位符不构成真实记录：

```json
{
  "group": "prd-design",
  "version": "v1",
  "reviewer": "实际独立调用者标识",
  "reviewed_outputs": "reviewed-output",
  "workflow_file": "workflow.md",
  "observations": [
    {"id":"workflow-execution","result":"NOT_RUN","reason":"尚未执行","evidence_refs":[]}
  ]
}
```

`result` 为 PASS、FAIL、NOT_RUN 或 UNKNOWN。每个已判定项须有具体理由、实际非空证据文件的相对路径；独立检查器不通过人名或 PASS 字段认证证据真实性。可信依据来自由宿主实际执行、审阅并固定的材料及现有保护边界。检查器只核对证据完整性、受审文件字节与独立判定，并明确其限制；不自动理解截图或验证自由文本的全部语义。

每组必需观察项（V2 另加 `upgrade-recheck`，说明真实新版本复验及未变更定制）：

| 组 | 必需观察项 |
|---|---|
| 所有组 | `workflow-execution`：实际工作流加载/执行记录；复制工作流文件本身不是加载证据 |
| prd-design | `original-requirements`、`render-mobile-desktop`、`interactive-states`、`customization-preserved` |
| data-reasoning | `computation-execution`、`reasoning-boundaries`、`customization-preserved` |
| market-research | `claim-support-and-conflicts`、`reasoning-boundaries`、`scope-preserved` |
| market-live | `search-and-original-pages`、`claim-support-and-dates`、`scope-preserved` |

PRD 证据记录实际 viewport、状态、操作及结果，配对应截图；数据证据记录实际程序、输入、计算输出及解释核对；研究证据定位原文、日期与结论并说明判断。不要用“检查完成”代替这些依据。欠缺或过期的宿主证据返回 ERROR/退出 2；有依据的明确业务失败返回 ASSERTION/退出 1；完整成功返回 0。

## 受保护 LOCAL 入口

```text
python -I -B verifier://check_business.py --group prd-design --version v1 --phase automatic --target /实际/workspace/outputs --fixture verifier://business/prd-design/manifest.json
python -I -B verifier://check_business.py --group prd-design --version v1 --phase reviewed --target /实际/workspace/outputs --fixture verifier://business/prd-design/manifest.json --host-evidence verifier://host-evidence/review.json
```

这表示实际 argv 的独立元素，不是 shell 展开命令。其他组替换 `--group` 和 `--fixture`；`--fixture` 和 `--host-evidence` 都传普通文件而非目录；`market-live` 仍读取 `business/market-research/manifest.json` 的固定元数据，成果按实时分支清单核对。`--version` 选择 v1/v2。

复用 LOCAL 资源 profile：network NONE、`STRUCTURED_V1`、`report_files:["summary.json"]`；每个 Case 的 `required_checks` 仅为对应的 `business-automatic` 或 `business-reviewed`。检查器使用宿主注入的 `FOUNDRY_CASE_ID`、`FOUNDRY_COMMAND_ID`、`FOUNDRY_REPORT_DIR`、`FOUNDRY_VERIFIER_ROOT` 写完整报告。phase automatic 的 `business_acceptance` 始终 false；reviewed 的 true 只表示上述独立宿主协作检查成功，不能自行形成控制器接受事件。

`checker_files` 显式包含所选组 `manifest.json`、`expected.json`、选定工作流、全部原始输入文件；reviewed 还包含整个已固定 host-evidence 文件集。所有依赖必须从受保护副本传入，禁止回退开发目录。CODEX 源输入只含任务/工作流/原输入和本公开约定；不要把独立预期或待审证据放入实现写域。模型、工具、实际路径和预算仍由真实准备 Readback 绑定，本文件不生成运行批准。
