# S3 宿主协作：生成、实际工具、独立复验

本工作流交付给外层 Codex 使用。它沿现有 LOCAL/CODEX 和受保护检查器运行，不新增执行器、暂停 API、预算库或审批。源码接入已准备，真正的模型、业务、原生恢复与跨 Program 验收在 S4 分别运行。自动文件检查通过不能表示三组业务全部通过。

## 1. 先绑定实际环境

使用本项目已有 `.venv/bin/python`；bindings 保留该绝对路径，不把它解析成系统 Python 后丢失虚拟环境。`python_read_roots` 按其实际 stdlib/依赖声明；Codex 路径和模型取当前受支持的本机配置。模型业务生成须允许模型服务；这与 DOC 离线、API 回环及离线独立检查的网络范围分开。

只把任务、选定工作流、公开输出约定及原输入发给生成者。检查器、独立预期和后续宿主审阅证据放在实施写域外。真实准备继续使用 `record-build-plan → capture-build-sources → prepare-build-authorization → read-build → approve-build-authorization → advance-build → read-build`；本文和材料生成器不产生任何 Review、授权或接受身份。

## 2. 生成后交回

固定业务组用 `business_requests.py --phase automatic`，实际 CODEX 读取所选 `workflows/v1.md` 或 `v2.md` 并产出合同文件；数据工作流实际运行 Python 计算并保留命令/输出记录。该阶段的 acceptance case 仅覆盖文件、数值、来源结构准备。

`ONE_ATTEMPT` 返回在整次实施与自动检查之后。外层先读原 command/attempt 和输出，保存实际加载工作流及执行记录。生成失败沿原生修复职责处理；不要为了插入宿主操作重新派发已经完成的生产命令。

## 3. 按任务调用实际工具并独立判断

| 任务 | 本次选择的宿主工具流程 | 独立核对 |
|---|---|---|
| PRD＋设计 | 使用 `mcp__cua_repl`。首次按当前工具说明选择浏览器并读取文档；通过已声明、允许的 HTTP 服务打开受审原型，调用 `getAXState()`、文档化的点击/输入和 `getScreenshot()`；按 viewport 能力文档设置 375、1280 两个宽度并在完成后复原。保存真实截图与逐状态操作记录 | 对照原始 R01–R08，检查 PRD、原型、定制、长文案、键盘和异常状态；不是只检查 `traceability.json` 自报字段 |
| 数据计算推理 | 用已绑定的 Python 执行交付工作流选择的计算方法；保留原输入、程序/命令、stdout/结果。保护检查器另外从原 CSV 用 Decimal/时区/修订/单位规则复算 | 核对实际执行记录和 `analysis.md`：未知金额、分母、显示舍入和情景区间不得被改成完整收入或确定增长 |
| 市场固定材料 | 工作流读取原始合成来源，独立宿主逐结论定位来源段落并核对冲突、日期、推断和未知 | 35/100 与 28/40 不组成增长率，29/39 的冲突不靠猜测消除；有引用不等于引用支持 |
| 市场实时分支 | 宿主按 `live-task.md` 调用 `web__run({search_query:[{q:实际查询}]})`，再 `open` 实际原始页面。保存查询、工具结果引用、URL、可见日期、检索时间、短支持片段及适用条件，产出 live 两个文件 | 实际打开两种产品的官方来源，独立核对功能/价格/试用及未知；这条分支只有 reviewed 入口，不能让没有搜索工具的 CODEX 预填最新事实 |

浏览器的具体能力和返回类型以当前工具文档为准；不假设仅安装浏览器就能控制窗口，不调用未暴露的截图或 viewport API。若网页/本机 URL 被工具策略拒绝，记录该工具欠项，不通过另一表面绕过。同样不把主聊天可用工具描述成 Generic 已自动调度它。首批文件原型不要求 Figma 原生对象。

2026-10-15 本轮接入探测已实际完成公开搜索、官方原文读取、公开 HTTPS 页的浏览器读回/截图及关闭自建标签。`file://` 原型探测被浏览器 URL 策略拒绝；未绕过，未运行本地业务 HTTP 原型、两个宽度或业务交互。这仅验证宿主接口可调用，不关闭任何 S4 业务场景。S4 应按当时允许的具体 URL 和已声明工具做实际准备；不可把这次公开页面截图复用为原型证据。

只清理本次创建的标签、服务及临时结果。临时原型服务的监听地址、根目录与停止句柄在实际范围中列明；关闭后核对它已停止，不查杀无关端口/进程。未完成服务清理或取证时如实保留状态。

## 4. 固定真实证据，再独立检查

由与成果生成相分离的宿主审阅流程填写普通审阅材料；最终 `host-evidence/review.json` 的格式及每组观察项见 [输出与证据约定](../business/OUTPUT_CONTRACTS.md)。证据须来自上述实际调用和原材料核对；可记录 FAIL、UNKNOWN、NOT_RUN，不能为通过检查补写不存在的 PASS。独立审阅可以由外层 Codex 执行，不要求增加逐项人工批准。

传给 `prepare_host_evidence.py --review` 的输入材料中，`evidence_refs` 相对 `--evidence-root`，不预加输出目录的 `evidence/`。例如真实文件位于 `/实际/工具记录/screenshot.png`，输入 `/实际/独立review.json` 中的一条观察为：

```json
{
  "reviewer": "实际独立审阅者",
  "observations": [
    {"id":"render-mobile-desktop","result":"UNKNOWN","reason":"示例尚未判定，实际使用时填写真实观察","evidence_refs":["screenshot.png"]}
  ]
}
```

将实际结果固定为新证据目录：

```text
python -I -B prepare_host_evidence.py --group prd-design --version v1 --outputs /实际/成果 --fixture /只读/business/prd-design --evidence-root /实际/工具记录 --review /实际/独立review.json --destination /新/host-evidence
```

helper 将该文件复制到 `/新/host-evidence/evidence/screenshot.png`，在输出 `/新/host-evidence/review.json` 中自动添加 `evidence/`：

```json
{
  "group": "prd-design",
  "version": "v1",
  "reviewer": "实际独立审阅者",
  "reviewed_outputs": "reviewed-output",
  "workflow_file": "workflow.md",
  "observations": [
    {"id":"render-mobile-desktop","result":"UNKNOWN","reason":"示例尚未判定，实际使用时填写真实观察","evidence_refs":["evidence/screenshot.png"]}
  ]
}
```

两例只展示一条观察的路径转换，不构成已运行证据；实际审阅材料须覆盖所选组的全部观察项。helper 复制所声明成果、工作流和证据字节，保留原结论，旧证据不覆盖；不会调用模型/浏览器/搜索，也不会认证审阅者或提交接受。随后把这些文件按 `checker_files` 固定进受保护副本。`business_requests.py --phase reviewed` 生成后续 LOCAL 复验材料：只复制已审的声明成果到本次隔离工作区，运行检查器，不重新计算或重新检索来代替原操作。

保护检查器核对固定的成果与工作流字节、独立数值/结构和宿主证据。缺证、未知或版本不匹配返回 ERROR，避免把准备问题当成产品返修；有真实依据的业务失败返回 ASSERTION。截图语义及自由文字仍由真实独立审阅负责，机器不因人名、URL 或 PASS 字段就认证真实性。

reviewed 的固定 LOCAL 复制器不具备业务修复能力，因此本示例使用材料中的 `preparation.advance_request` 模板 `{"advance_mode":"ONE_ATTEMPT"}`，补入本 reviewed Program 的真实 `program_id`、`prepared_event_id` 和当前 `expected_revision` 后调用既有 `advance-build`。该模板只是既有步进参数，不是批准或新协议；模式不跨调用继承。每次交回后先 `read-build` 取原 attempt、报告、消耗及真实结果；CLI 退出 0 或 `BUILD_CONTROL_RETURNED` 不等于业务通过；以读回的 attempt 状态和原控制器接受记录为准。若该 attempt 已为 ACCEPTED，不为取得已有接受再派发命令。

若结果为有依据的 FAIL，保留 `ASSERTION`，外层将实际失败证据、reviewed 身份及原生产者的真实记录关联到普通 handoff。然后读取原生产者的状态：原 CODEX 成果满足既有返修条件时，使用原 Program 的 `request-build-repair` 等适用入口及原授权、预算修复；由宿主产出的成果则沿原宿主流程修复，不为它补造 Program。不得把 reviewed 的失败 attempt 填进另一 Program 的 `basis_attempt_ids`，也不连续重派同一 LOCAL 复制器来消耗修复预算。ERROR 先补齐证据或处理设施问题，不据此修改业务产物。正常的真实缺陷修复可以运行必要生产步骤；禁止的是为补造取证记录而重放已完成生产者。

修复后独立复验受影响行为，将修后成果、工作流和实际观察固定为新证据，再准备新的 reviewed 材料及隔离复验工作区。旧失败、旧证据和全部实际消耗保留；新 reviewed 不覆盖旧受保护副本，原已接受成果的修复沿既有失效/返修流程。所需变更、授权及预算继续沿原有入口处理，不新增逐项审批，也不借新 reviewed 任务重置原生产者预算。

## 5. 恢复、升级和跨任务

先从原 `read-build`/命令记录恢复完整结果；完整捕获不重放，缺少报告按现有恢复行为处理。新 LOCAL 复验是明确的新验证任务，实际消耗归它自身；它不消除前序消耗，不再计算旧 attempt。宿主证据固定和 helper 诊断不是第二套控制台账。

V2 重新运行已升级工作流，检查新成果和保留定制；增加 `upgrade-recheck` 的实际依据。若成果有改动，旧审阅字节不再适用，只补相关重新审阅，保留历史材料。跨 Program 的普通 handoff 保存旧 control_db、program_id、prepared/proposal/attempt、workpack、产物及 `readback_revision` 的真实引用；当前 `basis_attempt_ids` 不填旧 Program 的 ID。不虚构 acceptance event 字段，也不把最后一个 command event 当成接受事件。

两次 DOC/API 组件升级及无 G 增量沿现有 helper 语义；只有实际接受后才单独保存 A/G lineage。旧效果未知仅影响依赖该效果的应用，正常核实、修复、独立候选和无关授权工作继续。G1/G2、报告取回计数和停止规则不因本示例改变。
