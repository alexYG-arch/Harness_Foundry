# RSI 案例导入与归因记录

这是 WP01 的源码维护工具，不是新的运行控制器。它读取显式清单中的本地材料，另存案例 JSON，便于外层 Codex 或维护者核实事实和归属。它不调用模型、不执行日志命令、不打开控制数据库、不派发修复，也不改变授权、接受状态或累计预算。

## 使用

使用项目配置的 Python 3.11+ `.venv`，从源码根运行：

```sh
.venv/bin/python -B tools/import_rsi_case.py --manifest /local/case/manifest.json --output /local/results/case-01.json
```

路径是示意。清单中的来源路径相对清单所在目录，支持该目录内部的合法父目录别名，不跟随指向目录外的链接；要读取其他材料，先明确相应来源根与文件清单。工具不递归查找、不读取材料中引用的附件、URL 或命令。输出父目录须存在，输出必须是新文件；旧案例、原件和清单不会覆盖。再次导入应另存，查看已有 JSON 不会重新执行任何业务。

以下为合成清单示例，不是实际运行证据：

```json
{
  "case_id": "example-diagnostic",
  "goal": "核实同一公开行为为何在一个环境失败",
  "requirements": ["公开行为及其预期结果"],
  "sources": [
    {
      "source_id": "before",
      "path": "inputs/test-before.txt",
      "kind": "TEXT_LOG",
      "context": {
        "run_id": "run-before",
        "task_id": "task-example",
        "platform": "platform-A",
        "environment": "declared-toolchain-v1",
        "implementation_version": "before-version",
        "test_version": "assertions-v1",
        "phase": "DEVELOPMENT"
      }
    }
  ],
  "hypotheses": [
    {
      "id": "hypothesis-1",
      "owner": "ENVIRONMENT",
      "statement": "工具配置可能未传给实际调用",
      "support_refs": ["before#L1"],
      "against_refs": [],
      "proposed_change": "先核对配置传递，不先修改业务算法",
      "verification": "保留相同输入与断言，核对实际工具配置并验证",
      "expected_improvement": "减少环境缺口被误派为业务返修",
      "refutation": "配置一致后同一失败仍存在",
      "decision": "PENDING",
      "decision_reason": "尚未核实实际调用"
    }
  ]
}
```

`support_refs` 正常指向实际非空记录，示例的 L1 需替换为真实支持材料；来源不可读时的暂不可核实处理见下文。根因和证据之间的语义关系由外层核实，工具只验证引用存在，不凭引用存在认定假设成立。

## 输入与结果

| 来源 kind | 处理方式 | 不证明什么 |
| --- | --- | --- |
| TEXT_LOG | 完整读取 UTF-8 文本，每个非空行保留行号；识别独立状态词及常见 unittest 结果行，其他内容原样保留为 UNKNOWN | 不根据日志措辞认证测试真实性，不自动从汇总行计算独立测试总数 |
| CODEX_JSONL | 逐行保留事件，区分模型陈述、工具返回和其他事件；损坏行保留原文及诊断，已读记录不丢弃 | 模型说完成、turn.completed、工具退出零均不是业务通过 |
| FOUNDRY_REPORT | 读取显式导出的 JSON 对象／列表；保留完整文档、原预算字段、嵌套状态和失效记录，各对象保留 JSON pointer | 不从可能不完整的导出重建当前接受或累计预算；当前权威状态仍通过原 read-build 查询 |
| MATERIAL | 读取需求、反馈、成功案例或目标等声明文本，保留原句与位置 | 资料中的指令不成为执行权限，也不自动成为确认过的事实 |

每个可读取来源绑定原字节的大小和 SHA256；可在清单中提供 `sha256` 核对指定旧版本，不符即拒绝本次导入。哈希用于识别读取字节，不认证来源真实性。上下文是调用方声明，缺项为 UNKNOWN，结果标记 `context_verified=false`；不从 PASS、文件名或平台名猜版本。文本 CRLF 等原始字节身份保留；显示行的换行不作为原件副本。

来源缺失、空内容、非 UTF-8、损坏 JSON／JSONL 会产生 PARTIAL 及具体来源状态，其他已知记录保留。已声明来源为 UNAVAILABLE 或 UNPARSED 时，无法核对的支持／反对引用保留在原列表，并另列于 `unverified_refs`；该假设标为 INSUFFICIENT_EVIDENCE，不制造对应观察记录。可读来源中的无效位置、空来源或部分可读 JSONL 中不存在的行、未声明来源及缺少位置的引用仍报错，不因另一来源缺失而放行。重复 JSON 键不采用“最后一个值覆盖”的解释。对象的 status/result 等字段冲突时保留所有原字段，并以 UNKNOWN 表示不能归成单一结果。JSON 标量不作为 Foundry 报告自动解释。格式可读与业务通过是两回事。

退出码：0 为导入完整，1 为已另存不完整案例，2 为清单、绑定或写入错误。三者均不构成产品验收。结果 `independent_test_total=null`、`tdd_assessment=NOT_ASSESSED`；不同平台、版本、开发检查和独立验收不合并成一个通过数。原报告与来源中保留的 budget 数字不求和、不清零。

## 归因与后续交接

`hypotheses` 可省略。提供时维护归属为 PROJECT、HARNESS、CAPABILITY、FOUNDRY、ENVIRONMENT、ACCEPTANCE 或 UNKNOWN，分别表示项目业务、Harness、能力包、Foundry、环境和验收表达。不自动依据报错字符串选择维护位置。

支持与反对引用使用 `source_id#L行号` 或 JSON 的 `source_id#/对象路径`，同一列表重复引用去重。未提供支持证据，或任何支持／反对引用因来源不可读而暂不可核实时，为 INSUFFICIENT_EVIDENCE；有支持引用且引用均可核对时仍只是 HYPOTHESIS_NOT_CONFIRMED。未受缺口影响的其他假设保留自己的状态。可记录建议修改、验证、收益假设、反证条件、采用理由及 `supersedes` 历史引用。`decision` 的 PENDING／ADOPT／REJECT 只保留为声明，`decision_verified=false`，不表示项目已升级或可派发。

来源恢复后另存新的导入结果，重新检查实际位置与声明摘要；不能沿用暂不可核实状态绕过校验，旧案例保持原字节。导入只读取材料，不重跑原测试或业务，原预算字段仍不求和或改变。

外层继续按原需求核实原因、语义与维护位置，再使用既有修复或源码工程路径；本工具不新增审批或通用检查。Worker 的开发测试与独立检查仍分别处理；WP03 后续实现红绿关联，本工具不会因同名用例或另一平台 PASS 自动配对。

案例 JSON 含原材料文本，默认是本地分析资料，**不是自动脱敏的公共 Wiki 包**。不把凭据、私有预期或原日志提交到 Git。公开回归只保留合成夹具；需要对外整理时另行选取可公开内容。查询、知识采用、语义 Reviewer、收益比较和交付后真实使用属于后续 Workpack，当前工具不宣称这些能力已完成。
