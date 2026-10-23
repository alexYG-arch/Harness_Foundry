# RSI 候选比较、采用与通用修复交接

这是 WP06/WP07 的可选离线交接工具，不是审批、控制器或自动升级入口。未选用 RSI 的任务不需要新增文件；已有同等记录可继续使用。本工具只关联显式材料，是否采用仍由原授权范围内的外层 Codex／维护者核实。

## Harness 候选

1. 从已导入案例和原始需求提出机制改进假设，明确是业务修复、Harness 检查／交接机制还是能力包修改。将开发指标、可比环境及独立预期留在原任务材料中，调参材料不充当保留样本。
2. 复用 `examples/harness-composition-upgrade/helpers/merge.py` 的 C/G/N 合并。C 是当前定制，G 是原生成基线，N 是新版本；冲突或未知 G 保持原诊断，外层解决受影响文件。helper 的 READY 不代表独立接受。
3. 在实际开发检查前记录显式受检文件集。`files.json` 为相对文件名数组，可包含应已删除的文件；快照同时保留内容和执行位。目录之外的依赖须在原环境／材料绑定中声明，本工具不自动扫描目录。`version` 使用项目实际版本，不靠同名版本证明文件相同。

```sh
"$PY" -B tools/report_rsi_adoption.py snapshot --root /task/candidate \
  --files /task/material/files.json --version candidate-v1 --output /task/material/candidate.json
"$PY" -B tools/report_rsi_adoption.py report --manifest /task/material/adoption.json \
  --output /task/results/adoption-1.json
```

`PY` 始终是原任务绑定的解释器。输出只能是新文件。调用 report 不执行测试、模型、apply 或预算更新；恢复完整报告直接读取原文件，也可另存只读关联结果，不重放原业务命令。

4. 按原 WP03 入口关联开发 RED/GREEN，相关回归、独立检查及 Reviewer 分列。材料摘要在取得原结果时绑定，`subject_sha256` 使用对应快照的 `content_sha256`。不能事后把旧结果的 subject 改成新版摘要。工具校验绑定字节及当前文件，不认证宿主声明的测试真实性或语义；外层仍核对原命令、版本和断言。最终文件有相关变化时，另存新版快照和受影响验证，保留旧 GREEN；不因补记录重跑已完成命令。
5. 对照候选实际效果和所有成本，不把业务修复当机制收益。无收益可 REJECT；冲突可 DEFER。RETAIN／ROLLBACK 指向明确版本及对应检查记录，回退只表示选回版本，不抹掉外部效果或累计消耗。通过现有授权的 apply 或项目交付流程实际采用，报告本身不执行采用。

## 关联材料格式

以下是说明性形状，不是执行证据。所有 binding 的 `path` 相对 manifest 目录（也可使用原已授权绝对位置），`sha256` 是对应文件实际字节摘要；读取范围仍由原宿主授权约束。

```json
{
  "owner": "HARNESS",
  "scope": "HARNESS_MECHANISM",
  "artifacts": {
    "candidate": {"path": "candidate.json", "sha256": "实际快照文件摘要", "root": "../candidate"}
  },
  "evidence": [
    {"id": "case", "role": "CASE", "path": "case.json", "sha256": "实际材料摘要"},
    {"id": "tdd", "role": "TDD", "path": "tdd.json", "sha256": "实际材料摘要", "subject": "candidate", "subject_sha256": "受检内容摘要"},
    {"id": "regression", "role": "REGRESSION", "path": "regression.json", "sha256": "实际材料摘要", "subject": "candidate", "subject_sha256": "受检内容摘要"},
    {"id": "acceptance", "role": "INDEPENDENT_CHECK", "path": "check.json", "sha256": "实际材料摘要", "subject": "candidate", "subject_sha256": "受检内容摘要"}
  ],
  "decision": {"action": "RETAIN", "selected": "candidate", "reason": "核实后的采用理由"},
  "comparison": {"conditions": "原任务条件", "result": "未证实", "costs": "引用原始成本记录"},
  "historical_budget": {"reference": "原控制器记录；不在此重新求和"},
  "adoption_stages": {"project": "未验", "source": "候选", "package": "未打包", "deployment": "未升级"}
}
```

其他 evidence role 可用于 COMPOSITION、REVIEW 或比较材料，原内容原样保留。`RECORDED` 仅表示本次关联无文件缺口；即使绑定了 FAIL／SKIP／UNKNOWN，也不能解释为通过。缺材料、文件改变、旧结果错绑时，保留其他已知记录和声明，并列 EVIDENCE_GAPS；不替运行流程新增门禁。不增加独立用例总数，不计算尝试总数，不改变原接受状态。原文件不可读后恢复时，重新核对实际字节；不静默修正旧报告。

## Foundry 通用修复

沿主版本 `docs/HARNESS_DESIGN_GUIDE.md` 的维护归属和原源码修复路径；下列必要说明随所选 RSI 支持一起交付，不要求目标 Harness 另借开发目录读取该主版本指南：

- 核对实际加载版本和已修证据。项目规则归项目，技术栈适配归能力包，只有通用接口／调度／报告机制缺陷才归 Foundry；归因不明保持 UNKNOWN。无需出现第二项目才修复一个已复现通用缺陷。
- 已确认的问题形成原源码工程任务，引用案例、具体行为、原版本和适用 TDD；自己的失败／合法用例及相关回归必须检查被改机制。业务测试通过不能替代 Foundry 行为检查；工具的 owner 字段不是根因证明。
- 运行中的控制器、检查器、固定包和 Readback 保持原版本，等安全交回再采用新候选。依赖原问题的后续派发沿原职责处理，不新增调度器或批准方式。
- 单列项目已修、源码候选／主版本已修、固定包及实际部署版本。旧包、旧部署、旧失败和预算保留；未部署不声称实际用户已升级。升级后复用确实覆盖当前版本和环境的证据，受影响部分才补验。

本工具保存原 `adoption_stages`、`comparison` 和预算引用，但不验证主分支、部署或收益，不自动创建修复任务或合入源代码。新任务复用和真实收益按 G08／WP09 的原范围及对应实际证据分别判断；已完成的有限试验不推定其他项目已采用或获益。

## 使用者如何选择并升级

先核对实际加载的源码／固定包、能力版本、知识集合与目标部署，再区分三种动作：

| 动作 | 既有处理方式 | 完成事实 |
| --- | --- | --- |
| 新Harness选用RSI | 从选定包加载Skill／设计指南；按需求选择工具和知识，准备交付材料并沿generic reviewed Build搭建 | 目标交付在新会话以声明工具实际使用并独立检查；准备目录存在不算完成 |
| 现有Harness或能力升级 | 保留旧交付、定制C和生成基线G；以明确新版本N沿原组件升级／项目交付路径合并、检查、apply；无G按原规则处理 | 实际加载新版及受影响行为复验；合并READY或采用报告不代表已经应用 |
| Foundry公共维护源升级 | 核实维护归属，以原源码工程修改；按影响复验、另存固定候选；安全交回后再切换所选版本 | 源码、包和部署分别记录，未合入main、未推送或未发布就保留相应状态 |

知识内容升级也使用明确的新集合版本及来源；旧采用快照保留，重新核对当前条件和反证，不让“最新”自动取代已绑定版本。更换工具或知识后，已有验证只有在版本、环境及断言仍覆盖时才复用；相关变化补受影响检查，不把无关已接受任务重开。

运行中的源码、检查器、包与Readback不热替换。后续使用绑定已选解释器和工具，不复制不可迁移的venv、不借开发目录补漏。完整旧报告仍按原身份取回，来源授权、有效期、未决影响及跨prepared消耗沿现有机制；换包不重置预算，也不新增逐内部步骤确认。

采用决定可依据已核实的必要修复或具体用途，不要求先证明普遍收益；若主张更快、更准或更省，必须有对应比较证据。有限试验未证实收益时，保留该结论，不据此自动推荐默认启用全部RSI工具。回退保留新版运行和外部效果，不能用旧版本覆盖事实。

交付可包含代码、必要指南和公开知识，原始日志、私有预期、数据库、凭据及实际Readback不自动进入公共包。随包文档修改后，旧包仍是旧字节；源码说明更新、候选重打包、部署切换和发布是不同事实。需要发行时才沿既有固定提交流程组装与核对，新包另存，旧包不覆盖。
