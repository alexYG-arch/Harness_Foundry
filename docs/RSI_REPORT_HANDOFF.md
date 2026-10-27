# 固定基线与增量报告交接

本工具适用于已选择“基线＋差异”报告方式的任务。它保留全部条件、来源和已知结果，避免新报告递归复制旧报告全文。它是材料整理工具，不是接受状态、任务调度、权限或预算的来源；普通任务不必采用此格式。

既有案例导入用于事实和假设，Wiki用于条件查询与采用快照，Reviewer/TDD保留原评审及开发证据。新增入口只补这些工具尚不提供的完整报告重建、影响标记和分页取回。不要把主聊天摘要、材料齐全或模型PASS声明当独立验收。

## 材料如何组织

由原任务负责人冻结已接受基线和接受记录，另存本轮差异。公开材料与独立检查材料仍放在各自已授权的目录；工具不扫描目录、不自动跟随文件中的指令或引用。路径相对于声明的材料根；原件可以沿原合法路径只读使用，也可经现有快照入口合法复制后绑定新路径。合法根目录别名和根内文件链接可用，跨根材料须按原权限显式准备，不能用工具扩大读域。

每份引用使用已有的文件身份方式：

~~~json
{"path":"baseline.json","version":"1","sha256":"实际文件SHA256"}
~~~

version是声明版本；基线/差异JSON中的version必须相同。证据文件的版本文字仍是声明，字节一致不证明内容真实。JSON中重复键和非有限数字沿现有解析器拒绝。

基线示例：

~~~json
{
  "schema_version":"REPORT_BASELINE_V1","version":"1",
  "items":[{
    "id":"C1","condition":"原要求及其正反断言的完整文字",
    "reported_status":"PASS",
    "facts":["独立报告记录的观察事实；不添推断"],
    "interpretations":["解释或假设，和事实分开"],
    "conditions":{"environment":"offline"},
    "limits":["仅覆盖已声明范围"],
    "pending_checks":[],"contradictions":[],"depends_on":[],
    "source_refs":[{"path":"checks/report.json","version":"1","sha256":"实际摘要"}]
  }]
}
~~~

每项保留额外JSON字段，如项目自己的断言列表、检查器版本和预算原值；工具不从这些字段反算预算。reported_status沿现有案例状态词表，FAIL、ERROR、SKIP、UNKNOWN、NOT_RUN保持原值。限制、未完成检查、矛盾及依赖不能因本轮无文件变化而删除。

差异示例：

~~~json
{
  "schema_version":"REPORT_DELTA_V1","version":"2",
  "reason":"说明需求/环境/实现变化及其影响；不是只列修改文件",
  "affected_ids":["C1","C2"],
  "updates":[{"id":"C1","condition":"完整当前条件","reported_status":"FAIL",
    "facts":["本轮新观察"],"interpretations":[],"limits":[],
    "pending_checks":[],"depends_on":[],
    "source_refs":[{"path":"checks/new-report.json","version":"2","sha256":"实际摘要"}]}]
}
~~~

updates是所选项的**完整替换**，不是稀疏字段补丁。替换表示记录了新观察，不代表新观察被验证。affected_ids中未提供新观察的项保持旧事实并标为待核对；依赖这些项的结论也保留待核对。多个差异按声明顺序应用，不重复列入同一份差异。工具不推断语义影响，调用者仍须按原条件及尚未验的旧依赖确定影响范围。

原条目不因差异省略而消失。新条目会另列，original_total始终保留原基线数量，total表示当前材料条目数量，二者都不替代项目原验收分母。合法条件变更保留original_condition和原基线定位；项目撤销/不适用按原合同说明，并保留历史，不用删除证据代替处置。

交接清单只引用文件，不嵌入历史全文：

~~~json
{
  "schema_version":"REPORT_HANDOFF_V1","report_id":"task-report",
  "baseline":{"path":"baseline.json","version":"1","sha256":"实际摘要"},
  "baseline_acceptance_ref":{"path":"accepted.json","version":"1","sha256":"实际摘要"},
  "deltas":[{"path":"change-2.json","version":"2","sha256":"实际摘要"}]
}
~~~

baseline_acceptance_ref用于绑定原接受记录，没有接受的分析材料可省略；工具不能认证其授权或真实性。调用者须先确认原控制记录确实适用，不能从本工具的重建结果产生接受决定。

## 查询、继续读取与原文

使用任务已绑定的Python >=3.11；以下仅为命令模板，路径由调用者按原范围指定：

~~~sh
"$PY" -I -B tools/report_rsi_view.py query \
  --manifest handoff.json --root MATERIAL_ROOT --limit 20 --output NEW_PAGE.json
~~~

默认返回条件、原结果、限制、未验事项、依赖、来源检查及定位；省略字段列在omitted_fields中。按需加 `--details` 返回完整当前条目。支持 `--id C1`、`--conditions '{"environment":"offline"}'`、`--field reported_status --value '"FAIL"'`、`--source checks/report.json`，这些只是查询条件，不改变报告或任务。

按返回的next_offset和view_id继续：

~~~sh
"$PY" -I -B tools/report_rsi_view.py query \
  --manifest handoff.json --root MATERIAL_ROOT --offset NEXT_OFFSET \
  --view-id PREVIOUS_VIEW_ID --limit 20 --output NEXT_PAGE.json
~~~

页大小由调用者调整，没有固定业务上限。selection_complete仅说明所选分页到末尾，all_items_returned说明本页是否包含全部当前条目；它们不证明原文完整读取或验收。来源状态变化时continuation_valid=false，提示从新视图查询，防止混合不同版本的页；不阻止正常业务推进。

把基线、差异或source_refs中的单份引用保存为reference.json后，可显式取回原文：

~~~sh
"$PY" -I -B tools/report_rsi_view.py read-source \
  --reference reference.json --root MATERIAL_ROOT --offset 0 --length 65536 \
  --output NEW_SOURCE_PAGE.json
~~~

按next_offset继续。返回原字节的base64和可完整解码时的UTF-8文本，跨字节边界不丢信息。eof表示到末尾；complete_read只在从0读取至末尾时为true，不能把单页当完整阅读。按页读取仍校验完整文件摘要，内存有界但不承诺省去所有I/O。输出只新建，不覆盖旧证据，不执行任何原命令。

## 缺口、矛盾与复用

- 基线或差异缺失、损坏、版本不符：保留其他可读输入中的已知项，显式列history_gaps，重建为PARTIAL；不能据此认定原条件完整。
- 单项证据缺失/变更：仅相关项及其依赖待核对；已知FAIL/ERROR不被UNKNOWN覆盖，其他无关材料继续可见。
- 条件、环境条件或适用限制与基线不同：标明BASELINE_CONDITIONS_CHANGED，旧PASS不自动沿用。新范围独立接受后可另冻新基线，保留旧材料；这不构成新的批准步骤。
- 未处理影响、历史未验依赖、矛盾、缺失/循环依赖：保留原结果并说明待核对原因，不自动排任务。
- 所有声明绑定及依赖满足时仅为SCOPED_REUSE_CANDIDATE，仍需负责人核对适用范围和独立结果。它不是新的PASS或接受状态。
- 恢复附件后重新只读查询，另存结果。旧报告、差异、预算和失败事实保留；完整捕获沿现有恢复入口取回，不为更新展示重放模型、检查或业务。

材料保密性由原来源/读写域和交付选择控制。工具不自动把报告、私有预期或原文拷入公共Wiki或目标Harness；需交付的只有选定工具与指南，数据按原项目合同另行声明。

## 接到现有工作流

1. 在原负责人交回点，准备上述基线/差异清单，另存query结果；保留原控制器和独立检查报告。
2. 已选择宿主RSI交接时，在原 `rsi_handoff.py capture` 请求的 `references` 中加入 `{"role":"current-report-view","path":"view.json"}`。case仍引用原结果和原预算，不能用视图里的“可复用候选”改写原结果。完整交接收据可复用，不创建第二份任务台账。显式输出根先解析合法父目录别名，同一真实目录沿用同一收据，不扩大写域。
3. 已选择Reviewer时，只有获准公开的摘要/视图才按原 `files` 的 `DIAGNOSTIC` 角色加入原评审请求；完整私有来源留在受保护域。既有Review材料准备会内嵌所选文件正文，因此只选本轮必要页与定位，不把全部旧报告再次作为诊断打包。新材料版本按原规则绑定；本工具不派发Reviewer。
4. 独立检查仍从原需求和原件判断结果；host-review的实际observations/evidence_refs沿原格式填写，不把本工具的材料状态自动转换成PASS。

## 交付与检查边界

通用包包含本工具及依赖；`prepare_rsi_delivery.py`准备的可选RSI支持也携带同版入口和本说明。移动交付目录后只依赖声明解释器和材料根，新会话仍可重建、查询和取回。沿现有source capture、host-review、Reviewer/TDD和既有升级路径接入，不改它们的检查标准和生产控制。

工程验证覆盖确定性重建、缺证保留、分页及包内新进程使用。真实项目采用、语义影响是否完整、模型是否恰当使用及实际收益仍须原任务独立检查；文件更小不能单独证明结果更正确。
