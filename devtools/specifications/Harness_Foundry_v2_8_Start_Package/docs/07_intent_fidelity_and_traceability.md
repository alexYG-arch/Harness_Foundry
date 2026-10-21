# 07｜意图保真与双向追溯

> 状态：目标 Start 执行包的生成规范，不是实现报告。本文要求生成者在目标工程中创建相应清单、校验器任务与证据契约；本文自身不证明这些文件、工具或校验能力已经存在。

## 1. 目的

新 Agent 或 Harness 的 Start 执行包不得只保留“总体目标”。它必须把用户提供的宪章、PRD、规则、图示、交互说明和约束转成可枚举、可定位、可验证的最小意图原子，并保持正向与反向追溯。

本文与以下规范共同使用：

- [目标 Start 执行包契约](03_target_start_package_contract.md)
- [阶段状态机](04_phase_state_machine.md)
- [Workpack 与执行模式](05_workpack_and_execution_modes.md)
- [校验架构](08_conformance_architecture.md)
- [验收与负向测试](11_acceptance_and_negative_tests.md)
- [用户调整策略](01_user_adjustment_policy.md)

## 2. 规范词

- **必须**：生成的目标包缺少该项时不得声明 ready。
- **不得**：违反即形成阻断 finding，不能靠解释性文字豁免。
- **可以**：可按目标工程裁剪，但裁剪结果必须记录。
- **意图保真 PASS**：只表示锁定范围内的来源、原子、实现责任和验证证据形成闭环；不等于 Harness 已安装或已通过外部 C4 认证。

## 3. 四个权威清单

生成的目标 Start 执行包必须声明以下文件的预期路径、schema、owner、生成时机和校验 Workpack。文件尚未生成时必须标记 `PLANNED`，不得填充虚假 PASS。

### 3.1 `canonical_source_manifest.json`

它固定“分母来自哪里”，至少包含：

```json
{
  "manifest_version": "1.0",
  "baseline_id": "INTENT-BASELINE-001",
  "sources": [
    {
      "source_id": "SRC-001",
      "authority": "USER_SUPPLIED",
      "path_or_uri": "<immutable-or-versioned-reference>",
      "content_hash": "sha256:<hash>",
      "format": "markdown",
      "scope": "IN_SCOPE",
      "precedence": 10
    }
  ],
  "excluded_sources": []
}
```

规则：

1. 每个来源必须有稳定 ID、内容 Hash、版本或不可变定位、权限范围和优先级。
2. 来源冲突不得由生成模型静默合并；必须进入 open question 或 Human Gate。
3. `excluded_sources` 必须记录排除理由、批准人和批准证据。
4. 外部来源默认只读；目标包引用其 Hash，不得为了方便改写原件。

### 3.2 `canonical_intent_manifest.json`

它锁定本轮认可的意图基线，至少绑定：

```text
baseline_id
canonical_source_manifest_hash
normative_atom_catalog_hash
atom_extraction_policy_version
open_question_set_hash
human_gate_receipt_hash
created_at
supersedes_baseline_id
```

只有用户或被授权的 Design Authority 可批准新基线。模型不得把自己的摘要当成新的 canonical intent。

### 3.3 `normative_atom_catalog.json`

每条 Intent Atom 必须是一条不可再删减而仍保持原意的规范性陈述。每个原子至少包含：

```text
atom_id
source_id + source_locator + source_excerpt_hash
subject + trigger + required_behavior
polarity
condition / exception
value + comparator + unit
ordering / dependency
default_behavior
cancel_behavior / retry_behavior / timeout_behavior
error_and_recovery_behavior
permission_or_role
acceptance_observation
criticality
status
```

原文没有某字段时写 `NOT_SPECIFIED`；不得自行补成事实。确需工程默认值时，创建 `ASSUMPTION` 或 `PROPOSED_DECISION`，并在用户批准后才进入 canonical baseline。

### 3.4 `atom_coverage_matrix.json`

覆盖矩阵必须逐原子记录：

```text
atom_id
source_locator
charter_outcome_id
requirement_id
owner_workpack_id
phase_and_gate
stage_spec_id
implementation_target
run_path_step_id
scenario_ids
checker_assertion_ids
expected_receipt_ids
current_evidence_refs
coverage_status
```

`coverage_status` 只能来自固定枚举：

```text
UNMAPPED
MAPPED_NO_IMPLEMENTATION
IMPLEMENTED_NO_TEST
TESTED_NO_TRUSTED_EVIDENCE
VERIFIED
EXPLICITLY_EXCLUDED
BLOCKED_BY_OPEN_QUESTION
```

禁止把 `MAPPED_*`、`IMPLEMENTED_*` 或 `TESTED_*` 显示成完成。

## 4. 原子化规则：禁止丢失与歪曲

生成者必须对下列语义分别建模，不能折叠成一句泛化描述。

| 语义类别 | 必须保留的内容 | 典型错误 |
|---|---|---|
| 数值与单位 | 值、单位、比较符、精度、边界 | `5 秒内` 被写成“及时” |
| 顺序 | 前驱、后继、可否并行、跳过条件 | P1/P2/P4 有文件便视为可跳 P3 |
| 否定 | `不得`、`仅`、`除非` 的极性和作用域 | “不得回退源码”被改成建议 |
| 默认值 | 未输入、首次进入、重置后的行为 | 只实现用户显式选择路径 |
| 条件与例外 | 触发器、角色、状态、例外边界 | 把条件规则改成全局规则 |
| 取消 | 入口、确认、回滚、结果状态 | 只保留成功按钮 |
| 重试 | 次数、退避、幂等、重试后状态 | 无限重试或重复副作用 |
| 超时 | 计时起点、阈值、终止与恢复 | 只记录 timeout 文案 |
| 错误与恢复 | 错误类型、用户动作、恢复位置 | 所有错误合成 generic error |
| 权限 | 谁可见、谁可执行、拒绝结果 | 只验证 UI 隐藏 |
| 中间态 | loading、pending、partial、cancelled | 只验证 final success |

一段来源同时含多个义务时必须拆成多个原子；跨段共同定义一个约束时可由一个原子引用多个 source locator，但不得丢掉任一 Hash。

## 5. 双向覆盖要求

### 5.1 正向覆盖

每个 `IN_SCOPE` 的规范性来源片段必须满足：

```text
Canonical Source
→ Intent Atom
→ Charter Outcome / Requirement
→ 单一 Owner Workpack
→ Phase / StageSpec / Run Path
→ Scenario / Checker Assertion
→ Expected Receipt
→ Trusted Evidence
```

未进入 Intent Atom 的来源片段必须被独立列为非规范性说明或显式排除，不能直接消失。

### 5.2 反向覆盖

每个生成的 requirement、Workpack、实现目标、场景、checker assertion、receipt 和 release claim，必须反向定位到：

```text
Intent Atom → Source Locator → Source Hash → Canonical Baseline
```

找不到来源的条目只能是已标记并获批的工程派生约束，不能伪装成用户需求。

### 5.3 两个独立分母

必须分别计算：

1. `source_to_atom_coverage`：来源规范片段是否全部进入原子或获批排除；
2. `atom_to_evidence_coverage`：每个原子是否走到可信验证证据。

不得从已生成的 Pack、checker 或实现代码反推覆盖分母。否则原子一开始被漏掉时仍可能显示 100%。

## 6. 变更与重基线

用户对文档做合理调整时，按[用户调整策略](01_user_adjustment_policy.md)执行，并且必须：

1. 创建 change request，引用旧、新来源 Hash；
2. 标记新增、修改、拆分、合并、删除的 Atom；
3. 生成 coverage diff 和影响范围；
4. 使受影响的 Workpack、Lock、Artifact、安装证据和 Certificate 失效；
5. 通过 Human Gate 后生成新 baseline；
6. 按[修复与失效传播](10_linkage_repair_and_invalidation.md)重新建设与认证。

模型可以改进组织、拆分文档和补足可执行指令，但不得在没有来源或批准的情况下改变需求含义。

## 7. 目标包必须生成的任务

目标 Start 执行包至少要包含以下 Workpack，而不是只复制本章：

```text
WP-INTENT-001  建立 canonical source manifest
WP-INTENT-002  提取并审查 intent atoms
WP-INTENT-003  建立正向/反向 coverage matrix
WP-INTENT-004  实现 intent fidelity checker
WP-INTENT-005  生成 mutation fixtures 与负向测试
WP-INTENT-006  把 baseline hash 接入阶段 Lock、Pack 与 Certificate
```

每个 Workpack 必须含输入、只读边界、输出、owner、前驱、完成定义、验证命令、失败路由和证据路径。

## 8. 最低门禁

下列任一情况必须 FAIL：

- canonical source 未锁 Hash；
- 来源分母由实现或 Pack 自己定义；
- 存在未映射且未获批排除的规范性片段；
- 原子缺少 source locator；
- 单位、比较符、顺序、否定、默认值或异常分支被摘要化；
- 只有正向映射，没有反向来源；
- 用“文件存在”替代 checker assertion 与可信 evidence；
- intent baseline 已变化但沿用旧 Artifact 或 Certificate。

具体变异用例见[验收与负向测试](11_acceptance_and_negative_tests.md)。
