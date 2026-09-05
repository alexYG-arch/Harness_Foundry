# GitHub Skill Video Explainer：Foundry 静态假阳性问题复盘与修复方案

## 0. 文档信息

| 字段 | 内容 |
|---|---|
| 文档状态 | `POSTMORTEM_AND_REMEDIATION_PROPOSAL_NOT_IMPLEMENTED` |
| 适用产品 | Harness Foundry v2.9 Start Package Compatibility Route |
| 案例 Program | `PROGRAM-GITHUB-SKILL-VIDEO-EXPLAINER-HARNESS-V1` |
| 复盘范围 | 现存 epoch 4–16 Candidate 与共享 Foundry Producer、Validator、Regression |
| 当前权威状态 | revision `106`，`CANDIDATE_READY_FOR_HUMAN_REVIEW` |
| 当前 State Hash | `ebb8aa43c86079f09d3c7aacd422094472c6c57a4209822372262ce6ea0e9d3b` |
| epoch 16 Requirement IR SHA-256 | `c6b87e1a4f95a6d4f88cb2a26e27e066fad88d418a4f4f47ea31469a8e02f1a0` |
| epoch 16 Candidate Content SHA-256 | `c9a16febc9676fb9eee570bc4b1605ea04a6203e51f8a109936639a9a592abf8` |
| 编写日期 | 2026-09-03 |
| 生命周期边界 | 本文不批准 Candidate，不执行 `REOPEN`、Freeze、Generate、Workpack、Driver 或 Harness |

本文记录一次明确的 Foundry 生产与验证体系缺陷：Candidate 可以通过全部静态检查，但其部分语义合同在阶段顺序、条件分支、跨 Artifact 数值关系和 baseline 行为保持方面不可满足。

本文是问题复盘与修复设计，不是新的 Requirement、Architecture Lock、授权、运行证据或完成证明。任何实际修复都必须先修改共享 Foundry Producer，再增加独立 Validator 与回归测试；不得直接编辑已发布 Candidate，也不得用单独放宽 Validator 的方式闭合。

## 1. 一句话结论

epoch 16 未通过 Human Review，不是 Candidate 随机损坏，也不能归因于目标 Harness 的运行失败。目标 Harness 尚未执行。当前确认的问题位于共享 Foundry：

```text
Requirement 中存在有效语义要求
→ Producer 投影出结构完整但语义不闭合的合同
→ Validator 只验证已声明结构和边
→ Regression 复用了 Producer 的错误理解
→ Static Validation = PASS
→ Human Review 重新检查可满足性时 = FAIL
```

这是 `COMMON_MODE_SEMANTIC_FALSE_PASS`：Producer、Validator 和测试共享相同盲区，导致自洽不等于正确。

## 2. “回归”的准确含义

本文中的“增加回归”是增加自动化回归测试，不是回退版本。

一个有效回归必须包含：

1. 一个最小、确定、可以重复触发历史缺陷的输入或 mutation；
2. 修复前测试稳定失败，并命中预期 Failure Code；
3. Producer 修复后生成正确合同；
4. 独立 Validator 能拒绝手工构造或 mutation 得到的错误合同；
5. 修复后测试稳定通过，且旧缺陷不能重新进入 Candidate；
6. 测试不依赖 Producer 的 `status=PASS` 或其他自报结论。

只有“新增字段存在”或“当前快照等于 golden JSON”不构成充分回归；这类测试可能把错误输出固化为新的 golden。

## 3. 已确认问题及跨 epoch 复现

现存 Candidate 可覆盖 epoch 4–16；epoch 1–3 输出目录已经不存在，因此本文不推断其具体文件内容。

| Finding ID | 问题 | 可确认持续范围 | 判定 |
|---|---|---:|---|
| `HF-SP-FP-001` | 最终 A/V drift 被要求写入 Render 前的 `AUDIO_ALIGNMENT_RECEIPT` | epoch 5–16 | 连续存在，不是 epoch 16 新随机回归 |
| `HF-SP-FP-002` | Object Motion 没有可重算的 word-to-motion `≤0.10s` 数值关系 | epoch 9–16 | `OBJECT_MOTION_IR` 出现后持续存在 |
| `HF-SP-FP-003` | `AUTHORIZED_TARGET_SKILL_RUN` Demo 分支引用执行 receipt，但 Demo 不依赖执行 Gate | epoch 10–16 | 分支自引入起即不可达 |
| `HF-SP-FP-004` | 约三分钟视频只要求最少 2 个 shot、1 个 transition | epoch 9–16 | baseline 的 10–14 scene 行为未被保持 |
| `HF-SP-FP-005` | 静态 Validator 与测试仍对上述输出给出 PASS | epoch 16 已复现 | 证明存在验证共同模式失效 |

### 3.1 `HF-SP-FP-001`：阶段证据不可用

错误合同：

```text
AUDIO_ALIGNMENT_RECEIPT
  depends_on = Narration Script + Local TTS
  required = final_av_drift_frames + absolute_final_av_drift_frames
```

但最终 A/V drift 只能在视频 Render/Mux 完成并读取最终视频字节后计算。Alignment 阶段尚不存在最终视频，因此该 receipt 无法诚实生产这些字段。

根因位置：

- Producer Schema：`src/harness_foundry_factory/semantic_contracts.py::_strengthen_artifact_schema`
- Producer Dependency：`src/harness_foundry_factory/semantic_contracts.py::_bind_artifact_dependencies`

正确归属：

- word anchor、音频 SHA、强制对齐误差属于 `AUDIO_ALIGNMENT_RECEIPT`；
- 最终 A/V drift 属于 `MEDIA_ACCEPTANCE_RECEIPT`；
- `AUDIO_VIDEO_DRIFT` Failure Code 不应由 Render 前的 Alignment receipt 关闭。

### 3.2 `HF-SP-FP-002`：跨 Artifact 数值关系被降级为自报标量

Requirement 明确要求：

```text
word-to-motion error <= 0.10 seconds
```

当前合同分别记录了：

- Alignment 中的 word anchors；
- Motion object 的 `audio_anchor_id`；
- Motion object 的 `enter_time` 和 motion segment 时间；
- 一个 `max_anchor_error_seconds` 标量。

但没有 Oracle 明确执行：

```text
for each motion object:
  anchor = resolve(alignment.word_anchors, object.audio_anchor_id)
  observed_error = abs(object.enter_time - anchor.start_seconds)
  require observed_error <= 0.10
```

现有 negative mutation 只修改 `max_anchor_error_seconds`，没有修改物体时间并重新计算跨 Artifact 差值。因此它能证明“标量超过阈值会失败”，不能证明“动画与声音实际同步”。

### 3.3 `HF-SP-FP-003`：条件分支不可达

Demo Schema 允许三种 provenance：

1. `OBSERVED_REPO_FIXTURE`；
2. `AUTHORIZED_TARGET_SKILL_RUN`；
3. `CLEARLY_LABELED_ILLUSTRATION`。

第二个分支要求：

- 当前且精确的 target Skill authorization；
- target Skill execution receipt；
- receipt SHA-256。

但 Demo 被路由到 MB-P1；Target Execution Gate 位于 MB-P2。Demo 的依赖只包括 Source、Function Matrix 和 Asset Plan，无法读取稍后阶段的 Gate receipt。

因此 Schema 中存在一个形式合法、运行拓扑中不可生产的分支。仅检查 DAG 无环不能发现这种错误，因为缺失的边不会形成环。

### 3.4 `HF-SP-FP-004`：baseline 行为等价性丢失

`SRC-BASELINE-CODEX-V090` 的视频 IR 将 episode、visual 与 narration scene 数量约束在 10–14。升级后的 `OBJECT_MOTION_IR` 只约束：

```text
shots.minItems = 2
scene_transition_count.minimum = 1
```

于是一个 175–185 秒视频可以用 2 个超长 shot 和 1 次 transition 通过静态 Schema，同时明显退化原有动态讲解节奏。

当前 baseline migration 主要检查：

- capability disposition 是否存在；
- target artifact ID 是否能解析；
- regression case ID 是否存在。

它没有比较 baseline 与 target 的可观察行为约束，因此“映射成功”被错误地等同于“能力保持或升级成功”。

## 4. 为什么推进到 epoch 16 才暴露

### 4.1 epoch 数不是完整语义审计次数

每次已发布 Candidate 都是不可变快照。一次修复后必须 `REOPEN`、重新 Freeze、重新 Generate，因此 epoch 数会增长。

epoch 4–16 的推进方式主要是：

```text
Human Review 发现一组具体问题
→ 修对应 Producer/Validator/测试
→ 生成下一 epoch
→ 再审查下一层问题
```

这表示进行了多轮定向修复，不表示每一轮都从 Requirement 到 Runtime 对全部语义重新模型检查。

### 4.2 检查了“存在”，没有检查“可满足”

前序回归主要覆盖：

- required field 是否存在；
- Schema 类型是否正确；
- Hash 和 reference 是否成对；
- artifact ID 是否能解析；
- 声明的 DAG 是否无环；
- invariant 是否有名称和 mutation target。

缺失的是：

- 生产该字段时，上游证据是否已经存在；
- 每个 `oneOf` 分支是否至少有一条可执行路径；
- 多个 Artifact 之间的自然语言阈值是否有重算公式；
- baseline 的数量、时序和效果约束是否被等价保留。

### 4.3 Validator 和 Producer 共享错误模型

当 Validator 只对 Producer 已生成的声明做一致性验证时，会出现：

```text
Producer 漏掉必要依赖
→ Validator 只遍历已声明依赖
→ 所有已声明依赖均合法
→ PASS
```

同理，如果测试直接断言 Producer 当前输出的依赖数组和字段集合，它验证的是“实现是否稳定”，不是“实现是否符合原始语义”。

### 4.4 未执行 Runtime 不是充分解释

epoch 16 的验证范围是 `AUTHORING_ONLY_STATIC_VALIDATION`，并明确记录：

- `runtime_tests_executed=false`；
- `commands_executed=false`；
- `external_authority_oracles_evaluated=false`；
- `runtime_claims_verified=false`。

因此它不能证明真实 TTS、Motion 或 Render 行为。然而本次四个问题均可在合同层静态发现；不能把“尚未执行 Runtime”作为它们长期未被发现的免责理由。

## 5. 系统根因

### 5.1 直接根因

| Root Cause ID | 根因 | 影响 |
|---|---|---|
| `RC-STAGE-OWNERSHIP-MISSING` | Artifact 字段没有声明最早可用阶段和证据来源 | Render 后指标进入 Render 前 receipt |
| `RC-BRANCH-REACHABILITY-MISSING` | DAG 只验证已声明边，不验证条件分支所需证据 | 合法 Schema 分支在运行时不可达 |
| `RC-CROSS-ARTIFACT-ORACLE-MISSING` | 阈值被投影为自报标量，没有输入、公式和重算 | 静态 PASS 无法证明实际同步 |
| `RC-BASELINE-BEHAVIOR-COMPRESSION` | migration 只保存 capability/ID，不保存可观察行为 | baseline 动态节奏静默退化 |
| `RC-REGRESSION-COMMON-MODE` | 测试与 Producer 复用同一结构假设 | 错误实现和错误期望一起 PASS |

### 5.2 过程根因

1. Review 以当轮 Finding 为边界，没有维护全局 invariant ledger；
2. 相邻合同增强后，没有重新运行跨阶段可满足性分析；
3. Negative mutation 追求“可解析”，但没有证明它改变了真实因变量；
4. baseline migration 没有 preservation map 和 behavior delta；
5. 重复问题指纹没有触发 Architecture Review，而是继续增加局部字段和校验。

## 6. 修复原则

修复必须遵循以下顺序：

```text
Requirement invariant carrier
→ Producer phase/branch/value semantics
→ Independent Validator reconstruction
→ Positive + Negative + Mutation regression
→ Full repository validation
→ 新 epoch Human Review
```

禁止以下伪闭环：

- 直接编辑已发布 Candidate；
- 只修改 Validator 让旧 Producer 输出通过；
- 只添加字段或 invariant 名称；
- 让 Validator 直接调用 Producer 的判断函数；
- 用 Producer 的 `status=PASS` 作为 Oracle；
- 只更新 golden snapshot；
- 把静态验证称为真实视频、TTS、Motion 或 Harness 运行完成。

## 7. 通用解决方案

### 7.1 建立 Invariant Ledger

每条用户可观察要求必须形成独立记录：

| 字段 | 必需含义 |
|---|---|
| `invariant_id` | 稳定标识 |
| `source_requirement_ref` | 原始 Requirement/Source 定位 |
| `subject_artifact_kind` | 被判断的 Artifact |
| `producer_stage` | 生产 Artifact 的阶段 |
| `required_evidence_kinds` | 重算所需输入 |
| `evidence_available_stage` | 最晚输入何时可用 |
| `formula_or_algorithm` | 不依赖自报结论的计算方法 |
| `threshold` | 明确上下界和单位 |
| `failure_code` | 失败语义 |
| `negative_mutation` | 保持 Schema 合法但违反 invariant 的变异 |
| `baseline_relation` | RETAIN、UPGRADE、REPLACE 或 REMOVE 及行为差异 |

Producer 生成前必须满足：

```text
producer_stage >= every required evidence available stage
```

否则返回 `ARTIFACT_EVIDENCE_NOT_AVAILABLE_AT_PRODUCTION_STAGE`。

### 7.2 增加 Stage Evidence Availability Checker

Validator 不采信 Producer 自报的阶段合法性，应从 Artifact Index 重建：

1. Artifact → Workpack/Stage；
2. required field/invariant → required evidence kinds；
3. evidence kind → producing Artifact/Stage；
4. 对每个字段和 invariant 比较生产顺序；
5. 缺输入、输入在未来阶段或输入只有不可达条件分支时失败。

建议 Failure Codes：

- `ARTIFACT_EVIDENCE_NOT_AVAILABLE_AT_PRODUCTION_STAGE`；
- `ARTIFACT_FIELD_STAGE_OWNERSHIP_INVALID`；
- `FINAL_MEDIA_METRIC_DECLARED_BEFORE_RENDER`。

### 7.3 增加 Conditional Branch Reachability Checker

对包含 `oneOf`、`anyOf` 或显式状态分支的 Artifact：

1. 枚举每个可 PASS 分支；
2. 收集分支 required fields；
3. 将字段映射到证据 Artifact；
4. 在同 Job、同 Source、允许阶段内寻找依赖路径；
5. 每个声明为受支持的分支必须至少有一条可达生产路径；
6. 默认关闭分支仍必须可被未来精确授权激活，不能只是 Schema 中的死代码。

建议 Failure Codes：

- `CONDITIONAL_ARTIFACT_BRANCH_UNREACHABLE`；
- `AUTHORIZED_BRANCH_EXECUTION_GATE_DEPENDENCY_MISSING`；
- `BRANCH_REQUIRED_RECEIPT_HAS_NO_PRODUCER`。

Demo 的推荐修复不是简单增加一个未来阶段依赖。应采用以下两种设计之一，并由 Architecture 明确选择：

#### 方案 A：拆分计划与结果

```text
MB-P1  DEMO_PLAN
MB-P2  TARGET_SKILL_EXECUTION_GATE_RECEIPT
MB-P2  DEMO_RESULT / BEFORE_AFTER_DEMO_CONTRACT
```

`DEMO_RESULT` 可以依赖 Gate；该方案阶段语义最清晰。

#### 方案 B：统一将 Demo 结果路由到 MB-P2

所有 provenance 分支都依赖 Gate receipt；未授权时 Gate receipt 记录 `DENIED_DEFAULT_OFF_NO_SIDE_EFFECT`。该方案改动较小，但必须证明不会给默认关闭分支增加隐式执行权。

### 7.4 增加 Cross-Artifact Numeric Oracle

数值要求必须声明：输入、Join Key、公式、阈值、单位和 mutation。

word-to-motion 的最小合同：

```json
{
  "invariant_id": "EVERY_OBJECT_WORD_TO_MOTION_ERROR_AT_MOST_0_10_SECONDS",
  "subject_artifact_kind": "OBJECT_MOTION_IR",
  "dependency_artifact_kind": "AUDIO_ALIGNMENT_RECEIPT",
  "join": {
    "subject_key": "/shots/*/objects/*/audio_anchor_id",
    "dependency_key": "/word_anchors/*/anchor_id"
  },
  "formula": "abs(object.enter_time - anchor.start_seconds)",
  "operator": "<=",
  "threshold": 0.10,
  "unit": "seconds",
  "failure_code": "MOTION_SYNC_TOLERANCE_EXCEEDED"
}
```

对应 negative mutation 必须修改实际输入，例如将 `object.enter_time` 移动到 `anchor.start_seconds + 0.101`，保持 JSON Schema 合法，并要求只有该 invariant 失败。

### 7.5 增加 Baseline Behavioral Equivalence Contract

Baseline Migration 每一行除了 artifact ID，还必须记录可观察行为：

```json
{
  "baseline_capability_id": "STATIC_LOCAL_CONTENT_COMPOSITION",
  "target_disposition": "REPLACE",
  "behavioral_invariants": [
    {
      "invariant_id": "VIDEO_SCENE_COUNT_RANGE",
      "baseline": {"minimum": 10, "maximum": 14},
      "target": {"minimum": 10, "maximum": 14},
      "relation": "PRESERVED"
    },
    {
      "invariant_id": "NON_INITIAL_TRANSITION_COUNT",
      "target_formula": "shot_count - 1",
      "relation": "STRENGTHENED_WITH_EXACT_RECOMPUTATION"
    }
  ]
}
```

Validator 必须从目标 Artifact Schema 和 Oracle 重新提取 target 行为，不采信 migration row 自报的 `relation=PRESERVED`。

建议 Failure Codes：

- `BASELINE_BEHAVIORAL_INVARIANT_MISSING`；
- `BASELINE_BEHAVIORAL_RANGE_WEAKENED`；
- `BASELINE_TARGET_ARTIFACT_KIND_MISMATCH`；
- `BASELINE_REPLACEMENT_HAS_NO_EFFECT_DELTA_ORACLE`。

### 7.6 增加重复问题指纹熔断

同一语义问题族连续跨两个 Candidate 出现时，不应继续默认进入字段级修复：

```text
same root-cause fingerprint appears again
→ ARCHITECTURE_REVIEW_REQUIRED
→ block next Freeze preparation
→ require invariant ledger and affected-graph audit
```

该熔断不增加普通流程的人工 Gate；只有重复指纹才升级。它防止用更多 receipt、Hash 和局部 Validator 掩盖生产架构缺口。

## 8. 必须新增的回归矩阵

| Test ID | 层级 | 变异或输入 | 修复后期望 |
|---|---|---|---|
| `REG-STAGE-001` | Producer | 编译 Video Artifact 合同 | Alignment 不包含 final A/V drift；Media 包含 |
| `REG-STAGE-002` | Validator | 向 Alignment 注入 `final_av_drift_frames` | `FINAL_MEDIA_METRIC_DECLARED_BEFORE_RENDER` |
| `REG-STAGE-003` | Validator | 将 Media final drift 输入依赖移除 | `ARTIFACT_EVIDENCE_NOT_AVAILABLE_AT_PRODUCTION_STAGE` |
| `REG-BRANCH-001` | Producer | 编译带 authorized Demo branch 的合同 | Demo result 对 Gate receipt 有同 Job 可达依赖 |
| `REG-BRANCH-002` | Validator | 删除 Demo → Gate 依赖 | `AUTHORIZED_BRANCH_EXECUTION_GATE_DEPENDENCY_MISSING` |
| `REG-BRANCH-003` | Validator | Gate 存在但属于另一 Job | `CONDITIONAL_ARTIFACT_BRANCH_UNREACHABLE` |
| `REG-NUMERIC-001` | Producer | 编译 Motion IR | 生成跨 Artifact join、公式、阈值和 Failure Code |
| `REG-NUMERIC-002` | Oracle | `enter_time = anchor.start + 0.100` | PASS，覆盖闭区间边界 |
| `REG-NUMERIC-003` | Oracle | `enter_time = anchor.start + 0.101` | `MOTION_SYNC_TOLERANCE_EXCEEDED` |
| `REG-NUMERIC-004` | Oracle | 只修改自报 `max_anchor_error_seconds` | 不能代替实际重算 |
| `REG-BASELINE-001` | Producer | 迁移 v0.9 scene contract | target 保留 10–14 scene 行为 |
| `REG-BASELINE-002` | Validator | 将 target `shots.minItems` 改为 2 | `BASELINE_BEHAVIORAL_RANGE_WEAKENED` |
| `REG-BASELINE-003` | Validator | target ID 解析到 Asset Binding 而非 Motion IR | `BASELINE_TARGET_ARTIFACT_KIND_MISMATCH` |
| `REG-COMMONMODE-001` | Meta | Producer 与 golden 同时接受错误依赖 | 独立 Validator mutation 仍必须 FAIL |

所有 negative regression 必须证明：

- mutation 确实应用到目标 JSON Pointer；
- mutation 后 JSON Schema 的预期 PASS/FAIL 状态明确；
- 命中的 Failure Code 精确；
- 未执行未授权副作用；
- 除目标 invariant 外的其他 invariant 仍 PASS，或明确声明联动失败集合。

## 9. Producer 修复清单

### P0：阻断下一次同类假阳性

- [ ] 从 `AUDIO_ALIGNMENT_RECEIPT` 移除最终视频 drift 字段与 `AUDIO_VIDEO_DRIFT` 关闭责任；
- [ ] 在 `MEDIA_ACCEPTANCE_RECEIPT` 保留并重算最终 drift；
- [ ] 为字段和 invariant 增加 evidence-stage metadata；
- [ ] 为 Demo 选择方案 A 或 B，并使所有支持分支可达；
- [ ] 为 Motion IR 生成 word-anchor join 和实际时间差公式；
- [ ] 将 v0.9 的 10–14 scene 行为写入 baseline behavioral contract；
- [ ] 修正 baseline target artifact 解析，禁止用相同前缀的附属 receipt 替代声明 artifact kind；
- [ ] 为每项新增 invariant 生成 schema-valid negative mutation recipe。

### P1：防止再次滑向局部补丁

- [ ] 建立跨 Artifact Invariant Ledger；
- [ ] 为每次 contract hydration 运行 stage availability 和 branch reachability；
- [ ] 将 repeated failure fingerprint 接入 Freeze 前检查；
- [ ] 把“字段存在测试”与“语义可满足测试”分为两个测试族；
- [ ] golden snapshot 只验证确定性，不作为语义正确性的唯一 Oracle。

## 10. Validator 修复清单

- [ ] 独立重建 Artifact、Workpack、Stage、Job 和分支依赖图；
- [ ] 检查字段最早可用阶段，而不只检查依赖边合法；
- [ ] 枚举每个支持的条件分支并证明至少一条可达路径；
- [ ] 解析 dependency bytes，执行跨 Artifact join 和数值重算；
- [ ] 比较 baseline 与 target 的可观察行为，不采信自报 preservation；
- [ ] 校验 target artifact kind，不能只按 ID 前缀选取；
- [ ] 对每个新增 Failure Code 提供正例、边界例、负例和 mutation 例；
- [ ] 不调用 Producer 的同一判断函数冒充独立验证。

## 11. 推荐实施顺序

### Step 1：先写失败回归

新增本文件第 8 节的 P0 回归，确认在当前代码上稳定失败。测试结果应保存测试名和 Failure Code，不需要生成新 Candidate。

### Step 2：修 Producer

依次修复：

1. Artifact 阶段归属；
2. Demo 路由与分支依赖；
3. Motion/Alignment 跨 Artifact 数值合同；
4. baseline behavioral preservation 和精确 target 解析。

### Step 3：修独立 Validator

Validator 依据 Requirement invariant 和生成后的 Artifact Graph 独立重建判断。禁止只把 Producer 新字段加入 allowlist。

### Step 4：运行验证

至少执行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/hffactory.py verify-spec --json
python3 tools/validate_skill.py
git diff --check
```

若 workflow 文件或 core capability 受到影响，再执行对应 `validate-core` 和证据投影检查。

### Step 5：重新进入生命周期

代码与回归闭合不自动授权 Candidate 生命周期推进。后续只能由用户显式：

1. `REOPEN epoch 16`；
2. 绑定新的空 output root；
3. 请求并确认新 Requirement Freeze；
4. 单独授权 Generate；
5. 对新 Candidate 重新开展 Human Review。

旧 Freeze、Generate 授权和 Human Review 状态均不得沿用。

## 12. 完成定义

只有同时满足以下条件，才能称为“Foundry 根因已修复”：

- [ ] 第 8 节全部 P0 regression 在修复前可复现、修复后 PASS；
- [ ] Producer 不再生成四类错误合同；
- [ ] 独立 Validator 能拒绝手工 mutation 的错误合同；
- [ ] 全量 repository regression PASS；
- [ ] `verify-spec`、`validate_skill`、`git diff --check` PASS；
- [ ] 未直接编辑任何旧 Candidate；
- [ ] 没有 Validator-only closure；
- [ ] 新 epoch Candidate 静态验证 PASS；
- [ ] 新 epoch Human Review 对四类 Finding 逐项给出闭合证据；
- [ ] 仍不把静态结果称为真实 Harness、TTS、Motion 或视频运行成功。

若只完成前七项，可以声明 `FOUNDRY_PRODUCER_VALIDATOR_REPAIR_VERIFIED`；在新 Candidate Human Review 前，不得声明 `START_PACKAGE_ACCEPTED`。在 Workpack、Driver 和 Harness 实际执行前，不得声明运行实现或视频生成通过。

## 13. 与现有 Foundry 文档的关系

- `docs/HARNESS_FOUNDRY_V2_9_ARCHITECTURE_CORRECTION_PLAN.md`：提供 Producer-first、Complexity Governor 和重复故障升级的上层原则；
- `docs/START_PACKAGE_TRUST_PRINCIPLES_LIMITATIONS_AND_CODEX_THREE_CLI.md`：说明 Validator 自测悖论、mutation testing 和独立校验边界；
- `docs/HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN.md`：仍是 v2.9 当前总体升级提案；
- 本文：把 GitHub Skill Video Explainer 的 epoch 4–16 事实转成可实现、可回归、可验收的专项修复合同。

本文不取代上述规范，也不改变 Factory SQLite 中的权威 Program 状态。
