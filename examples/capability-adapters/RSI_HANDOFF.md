# 所选修复过程的 RSI 交接

此入口供外层 Codex 在现有问题核实、子任务交回和安全收尾位置使用。任务已选择 RSI 时，外层按这里的步骤主动处理，不等待用户再说“执行 RSI”。未选任务照常运行。它不创建后台监听器、控制器或新审批，也不执行修复、测试、模型、Git、更新或遥测。

## 何时调用，谁负责

1. 沿原 `read-build`／报告恢复入口取回完整事实。子任务交回修改和证据，当前负责外层登记同一个问题；不得中断正在运行的子进程或只读最后一条模型消息猜状态。
2. 有方法缺口时，在对应修复前用原 `tools/rsi_wiki.py query` 查询已选集合，核对来源、版本、条件、反例和限制，再用 `record` 保存采用或不采用理由。已有足够方法、无命中或不适用时继续原路径，不要求每次查询。
3. 当前修改责任人按原授权核实、修复、复验。独立检查和原控制器继续决定接受；其他工具的结果不自动成为 Foundry Reviewer 或 TDD 结果。不对同一版本启动第二套修复，不为补 RED 重放业务。
4. 在原允许的观察或交回点，用下述 `capture` 关联案例和适用红绿。已有等价记录可以只引用。Reviewer 仍用原 prepare/plan/retrieve，采用仍用原 snapshot/report；本入口只绑定所提供引用的字节，不认证那些报告的语义、批准或来源链。
5. 有可复用经验时先整理候选，再用 `collection` 形成所选集合的新版本。新的实际任务从自己的问题查询新集合，并独立检查结果。推广知识或公共修复不成为原业务收尾的新条件；已约定的知识交付仍须满足。

不同工具及环境各自绑定，不修改全局 PATH。配置块归原管理器，Foundry 生成配置归其原升级入口；TDD、外部 Review 和独立接受分列。原业务尝试、模型 turn、检查、远端调用与成本只引用原记录，不建立另一份预算账本。

## 案例和红绿关联

用本任务绑定的 Python >=3.11 调用：

```sh
"$PY" -I -B examples/capability-adapters/rsi_handoff.py capture \
  --manifest /declared/analysis/handoff.json --output /declared/analysis/revisions
```

以下为结构示例，路径相对于该 manifest 所在目录。原报告由已授权宿主提供快照，工具不从日志中的路径追读其他材料：

```json
{
  "enabled": true,
  "identity": {"project":"example", "task":"build", "issue":"issue-1"},
  "phase":"repair-return",
  "context": {"prepared":"original-prepared", "attempt":"original-attempt", "command":"original-command"},
  "case": {
    "case_id":"issue-1", "goal":"核实公开行为", "requirements":["公开条件"],
    "sources":[{"source_id":"report", "path":"observed.json", "kind":"FOUNDRY_REPORT"}]
  },
  "references":[{"role":"controller-report", "path":"observed.json"}]
}
```

`case` 原样使用 `import_rsi_case` 的格式；可选 `tdd` 原样使用 `report_rsi_tdd` 的 association 格式。不可可靠映射的 Node、JUnit 或远端记录保留原文及证据不足，不把 PASS 字样变成结构化红绿。选中测试、整套回归和独立结果继续分别保存，合法 GREEN_ONLY／不适用不改成失败。`context` 可引用版本、生产尝试、只复验身份和预算原报告，不求和或重新扣减。

identity 使用原项目/任务/问题身份，无问题 ID 时在原工作记录中给出本地关联。不要以日志措辞、相似错误或 prepared 单独充当问题身份。同一问题跨 prepared 保留 identity，context 记录新增事实；相似文字的另一项目或问题不会自动归并。

输出默认是 **本地分析资料**，可能含原文、私有判定或凭据。不要把整个 revisions 目录交给 Worker、公共 Wiki 或发行包。给各接收者的材料由宿主按已有权限选取／脱敏，另存实际字节与受控原来源映射；PUBLIC 标签、摘要或成功导入不是公开许可。

## 恢复和失败

外层在原工作记录保存返回的 directory 引用，子任务不同时写同一条目。revisions 是指定材料目录，不是新的权威状态库。

- 同身份、阶段、输入实际字节和工具版本已有完整输出：校验后返回原目录，不再导入或执行任何原命令。
- 输出完整但外层尚未登记引用：取回返回的引用补记。输出文件完整但 completion 未写：核对输入和输出后只补 receipt，不回写旧产物。
- 部分文件、绑定不符或已损坏：保留原目录，另存修订。新证据、来源恢复、解释／工具版本变化也另存，不抹去原缺口。
- 来源暂不可读：保留其他事实和引用，结果为 PARTIAL；恢复后重新核对。可读来源中的无效引用继续报错。
- 文件／案例／知识交接错误返回 HANDOFF_INCOMPLETE；CLI 非零码只表示本交接缺口，不改变业务结果、接受或预算。外层继续不依赖该材料的合法工作；不得把交接失败伪装成自动 RSI 已完成。

只有当前外层一个写入者登记；不承诺仅凭 issue ID 获得多进程“恰好一次”。目录中的 input/completion 是可检查的材料绑定，不是批准、锁或哈希事件链。

## 候选加入可查询集合

原 `tools/rsi_wiki.py propose` 只生成候选。先使用该入口形成候选，按权限整理可交付来源，然后调用：

```sh
"$PY" -I -B examples/capability-adapters/rsi_handoff.py collection \
  --manifest /declared/curated/selection.json --output /declared/analysis/collections
```

```json
{
  "enabled":true,
  "identity":{"project":"example","task":"build","issue":"issue-1"},
  "phase":"knowledge-return",
  "collection":{"id":"selected","version":"2","visibility":"PROJECT"},
  "previous_config":"previous-wiki.json",
  "entries":["entries/method.json"], "updates":[],
  "files":[
    {"source":"candidate.json","path":"entries/method.json","audience":"PROJECT","reason":"所选方法候选"},
    {"source":"public-check.json","path":"evidence/check.json","audience":"PROJECT","reason":"已筛选合成回归结果"}
  ]
}
```

这是**完整的下一版集合选择**：保留哪些旧 entries、updates、来源就明确列出哪些文件；没有旧版时省略 previous_config。该文件只读取旧配置身份，新版另存，不回改旧查询、采用或撤回记录。工具不自动选全局公共集合，不自动搜索原始日志或复制案例。audience/reason 是宿主说明，工具不是脱敏器；凭据及私有预期仍由原材料边界排除。

返回目录中的 `wiki.json` 指向同目录的 `collection/`。用原 query/record 查询与记录选择。`PREPARED` 只说明材料已组装；来源缺失、状态、条件、撤回及反例在查询时仍显示，不因组装成功得到 VERIFIED。条目的原状态保留；VERIFIED_SCOPED 仍需实际验证范围，语义由独立检查负责。

新集合与准备记录分开：交付只选择 `wiki.json` 和获准的 collection 文件，input/completion 留在分析域。本辅助入口只整理宿主材料；目标交付携带此入口、自动触发及新会话实际使用仍需按所选合同另行核验。现有 prepare_rsi_delivery 不因本说明自动增加目标文件或权限。

## 当前验证边界

工程测试可覆盖材料绑定、恢复、私有内容隔离、混用命名与原预算保留；不能替代真实模型正常流程中主动触发、真实服务、完整目标交付、部署或收益。未做的分支保留未验。协议 2.9、原 R3 与既有分母不变。
