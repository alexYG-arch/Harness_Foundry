# 项目成果与宿主观察交接

此包为 PRD／设计与市场调研提供可选择的工作流及薄交接工具。项目决定原输入、产物、实际宿主和独立预期；本包不提供通用设计评分、研究结论或自动业务引擎。原 S3 固定业务示例保持原合同。

`prd.md` 与 `market.md` 交给目标工作流；按本次任务选择需要的规则。公开 `task.json` 例如：

```json
{
  "task_id": "本项目本次新需求",
  "workflow": "workflow.md",
  "inputs": {"brief": "inputs/brief.md", "customization": "inputs/user-config.json"},
  "outputs": ["prd.md", "prototype/index.html"],
  "host_tools": ["当前独立宿主用 mcp__cua_repl 打开本次声明 URL、操作并保存截图；具体入口和视口见任务"]
}
```

文件路径相对 task 所在目录；outputs 相对明确传入的成果目录，允许子目录。只复制声明的普通文件，不递归收集整个工程。`host_tools` 说明实际交接安排，不是工具发现、安装、权限或执行证明；当前 CODEX 子任务不自动继承外层浏览器或检索工具。项目已有 renderer、原型、资料处理 CLI 可继续作为项目交付，不要求改写成公共模块。

独立宿主按原需求执行实际工具并判断后，另存普通 review JSON：`reviewer` 为实际审阅者，`observations` 为包含 `id/result/reason/evidence_refs` 的列表。result 可为 PASS、FAIL、UNKNOWN、NOT_RUN；证据引用相对实际 evidence-root。例如 `{"id":"input-retention","result":"NOT_RUN","reason":"本次尚未操作","evidence_refs":[]}`。未观察不得填 PASS。观察的实际内容和真实性由独立宿主负责，文件名、人名、URL、自填 PASS 以及本包快照均不能认证它们。

宿主在已有授权范围运行：

```text
python -I -B snapshot.py --task /project/task.json --outputs /result/current --evidence-root /host/actual-records --review /host/review.json --destination /host/new-snapshot
```

此命令实际复制任务、所选工作流、全部声明输入/产物和所引用证据的字节，写出 `snapshot.json`；不运行模型、浏览器、搜索、renderer 或控制命令。新目录与上述输入根分开，旧目录不覆盖。读入完整后才写；写入异常保留局部结果供诊断，不自动清空重跑。

项目的独立 expectation 另存保护域，如 `{"task_id":"本项目本次新需求","required_observations":["original-requirements","input-retention"]}`。必需观察来自原需求和独立检查设计，不能从生产者或 review 已填的行反推。没有固定数量、业务状态名、视口、来源数量或得分阈值。

将 `check_review.py`、原 task 及其 workflow/inputs（按原相对布局）、独立 expectation、snapshot 全部声明到现有 `preparation.verifier_inputs`／`checker_files`，由原 Generic 建立受保护副本。snapshot 内也仅列出实际文件，不把目录当作自动递归资源。独立检查命令使用实际保护映射：

```text
python -I -B verifier://host-review/check_review.py --task verifier://project/task.json --expectation verifier://project-expectation.json --snapshot verifier://host-snapshot/snapshot.json --outputs /current/results
```

`--snapshot` 传 `snapshot.json` 普通文件，不能传目录；其余捕获文件仍须逐个列入 checker_files。保护环境中检查器自身、task、独立 expectation 和 snapshot 都必须来自 `FOUNDRY_VERIFIER_ROOT`；task 的相对依赖亦在该保护布局内。检查器是独立单文件，不从未保护的公共包导入判定。报告写 `FOUNDRY_REPORT_DIR/summary.json`，或单独 `--report` 新文件，使用既有 STRUCTURED_V1 case/command 绑定与归档。当前成果与快照逐字节比较；task、workflow、输入或成果改变时旧观察只保留为旧证据，不能用来证明新版本。

缺证、未完成观察、重复观察 ID、缺理由或错误绑定为 ERROR；完整、有证据的 FAIL 为 ASSERTION。必需观察清单完全覆盖且已提供观察均完整 PASS 时，报告仅表示“字节绑定及所提供独立观察核对通过”，不证明截图/自然语言语义真实，也不授予业务接受。额外已提供 FAIL 保留为问题，不因不在必需清单而丢弃。

同一批已提交观察可以同时包含有证 FAIL 和未完成项。检查器在 task／输入／成果字节绑定一致后读完其余可读观察，整体仍以 ERROR 表示证据不完整，`findings` 保留完整、有证的失败，不因行顺序漏记。外层将这些已核实缺陷照常交接原生产者；缺证项先补证，不将其推断为产品失败。额外观察既然已作为本次审阅提交，其 UNKNOWN／NOT_RUN 也表示本次报告尚不完整；这不增加项目必需观察或其他任务的通用义务。版本绑定已不一致时，旧失败仍在旧快照中，不凭它判断新成果。

沿原 automatic → 宿主实际观察 → reviewed LOCAL 路径：整次生产 attempt 交回后操作工具；ONE_ATTEMPT 不是生成与检查之间的暂停接口。reviewed 只复制已审成果并检查，不重跑生产工具来补造证据。真实业务 FAIL 交回原生产者按既有修复/授权/预算处理；ERROR 先修证据或设施，不据此改业务。修后固定新的成果与相关观察，保留旧证据及实际消耗。报告取回和重检读取已捕获数据，不重新搜索、渲染或计算；需要观察新版本时明确执行新的相关观察。

工程测试中的小文件和观察是明确合成夹具，仅验证交接、绑定、分类和不重放。新会话 PRD 需求变体的实际浏览器交互、MARKET 新子问题的实际检索、目标 Harness 闭环及第二设备仍需各自真实证据。
