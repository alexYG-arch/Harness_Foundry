# Harness Foundry v2.9 来源案例 001：V-SCDSL 语义执行与多样性假阳性

## 0. 文档边界

| 字段 | 内容 |
|---|---|
| 文档状态 | `NON_NORMATIVE_SOURCE_CASE` |
| 案例编号 | `SOURCE_CASE_001` |
| 来源平台提案 | `HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN.md / PROPOSAL-R8_SCOPE_CORRECTED` |
| R7拆分前快照 | `HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN_R7_PRE_3_0_SPLIT_ARCHIVE.md` |
| R6案例偏重快照 | `HARNESS_FOUNDRY_V2_9_SEMANTIC_CONFORMANCE_UPGRADE_PLAN_R6_CASE_HEAVY_ARCHIVE.md` |
| 允许用途 | 根因回溯、Target Profile authoring、Fixture/Canary设计、Case-to-Core候选论证 |
| 禁止用途 | Normative Core默认值、平台状态机、CLI、Gate、Stage/Subharness拓扑、认证结论或执行授权 |

本文件保存从主提案物理移出的案例内容。它不能被Core编译器读取，不能在加载时改变Core控制流，也不能单独把任何案例观察晋升为平台规则。

依赖方向只能是：

```text
SOURCE_CASE_001
→ VSCDSL Target Profile
→ 已冻结的Core Extension Point
```

## 1. 案例到平台候选的晋升状态

| 案例观察 | 初始分类 | 当前Core处理 | 晋升状态 |
|---|---|---|---|
| 结构唯一和自报PASS不能证明语义差异 | `PLATFORM_INVARIANT_DEFECT`候选 | Evidence兼容性、独立Oracle与禁止自证 | 需非来源Profile复现或形式化不变量证明 |
| 目标Executor没有原子化 | `PLATFORM_INVARIANT_DEFECT`候选 | Requirement Type、Executor Binding与Runtime Proof | 需跨领域复现 |
| 多图人物不得交换 | `PROFILE_VARIATION` | Target Profile Domain Rule | 不晋升Core |
| 固定候选数量与多路调用拓扑 | `PROFILE_VARIATION` | Target Profile Run Strategy/Topology | 不晋升Core |
| JSX只能静态解析 | `PROFILE_VARIATION + GOVERNANCE_POLICY` | Profile工具约束与通用禁止执行未授权Payload | 只晋升领域无关的权限边界 |
| 历史Active Manifest容易被误读 | `IMPLEMENTATION_DEFECT`或发布发现性问题 | Release Index/Current Pointer | 不由本案例直接新增平台链路 |

## 2. 案例要求、Finding与现场证据

### 2.1 核心 Requirement

本次需求核心包括：

1. 输入主题、创意或玩法后，从知识库选取并匹配内容；
2. 调用 Codex CLI 完成相关且多路差异化的语义推理；
3. 生成 30 个符合 V-SCDSL 规范的视频 Prompt；
4. 单图只需明确保持上传人物特征；
5. 多图必须明确区分 image A、image B 与角色，禁止混合或交换；
6. 模糊主题要产生全概念差异化结果；
7. 具象和详细描述要在镜头、音乐、节奏、机制和叙事上延展；
8. Markdown 和 JSX 知识资源必须进入推理过程；
9. JSX 只能静态解析，不能执行；
10. 整个修复应符合宪章的正规授权、执行、验证和晋级流程。

### 2.2 原始五类 Finding 的复核

#### 3.2.1 `CODEX_SEMANTIC_EXECUTOR_ABSENT`

要求需要真实 Codex CLI 多路语义推理，但实现可能只完成确定性模板组合、序列化或固定配方轮转。

问题本质：

```text
required_executor = Codex semantic reasoning
actual_behavior = deterministic template generation
```

仅有 Codex 作为 Coding Agent 的构建回执，不能证明最终 Harness 在处理用户 Input 时调用了 Codex 语义执行器。

#### 3.2.2 `PORTFOLIO_SEMANTIC_DIVERSITY_FALSE_POSITIVE`

30 条输出可能主要依靠以下因素形成表面差异：

- 不同编号；
- 不同时长；
- `recipe-NN`；
- 少量场景名替换；
- 相同叙事骨架的近义改写；
- 固定模板的轮转。

如果实现直接声明：

```json
{
  "whole_concept_duplicates": 0,
  "coverage": 1.0,
  "status": "PASS"
}
```

而验证器不从 30 条原始 Prompt 重新计算，就会产生假阳性。

#### 3.2.3 `IDENTITY_REFERENCE_PROMPT_OVERCONSTRAINED`

用户要求的是简洁身份锁定：

```text
单图：全片保持 image_A 中人物可识别特征和身份一致。
多图：明确 image_A/image_B 与角色映射，禁止混合、交换或新增人物。
```

旧实现可能把下列结构化治理信息堆入模型 Prompt：

- 图片 Hash；
- 权利与同意记录；
- 完整 Reference Binding；
- 未经用户文字明确要求的五官、发型、体型、服装推断。

这导致结构化 Bundle 虽然完整，模型 Prompt 却偏离用户意图。

#### 3.2.4 `DIVERSITY_CHECKER_INSUFFICIENT`

External Lab 的差异性检查未能有效拒绝：

- 仅时长不同；
- 编号伪唯一；
- 固定模板轮转；
- 场景未真正进入 Prompt；
- 重复故事结构；
- 抽象占位词；
- 自报 PASS 与真实内容不一致。

这说明 Validator 检查了声明字段，却没有完全独立地从原始结果计算语义差异。

#### 3.2.5 `ACTIVE_RELEASE_POINTER_AMBIGUOUS`

原检查将“v0.1 Active Instance Manifest 仍存在”推断为 `SOURCE_RELEASE_METADATA_STALE`。进一步回溯后，该结论不成立：v0.2 有独立的 Certification Matrix、C4、Certificate、Installation Receipt、Active Instance Manifest 和独立回读，当前安装目标也绑定 v0.2 wheel。

保留下来的真实问题是：跨版本浏览时若没有唯一的 current pointer 或索引，读者可能先看到历史 v0.1 清单并误判当前版本。该问题属于发布发现性与版本指针治理，不是 v0.2 证书缺失，也不能作为否定 v0.2 安装绑定的证据。

### 2.3 为什么 Start Package、校验和 Linkage 仍没有阻止问题

#### 3.3.1 Start Package 冻结了要求，但没有自动生成有效 Oracle

Start Package 可以声明“必须真实调用 Codex CLI”，但如果没有同时规定：

- 要保存哪些 Invocation Receipt；
- 如何证明模型与推理强度；
- 如何计算调用次数；
- 如何证明 Lane 互斥；
- 哪些代理实现被禁止；
- External Lab 如何独立回读；

下游仍可能用形式相似的实现替代真实要求。

#### 3.3.2 Coverage Edge 证明路由，不证明履约

当前：

```text
Requirement Atom → Workpack → Stage → Owner
```

能够证明 Requirement 没有被遗漏或错误路由，但不能证明 Workpack 的实现真正满足 Requirement。

#### 3.3.3 结构验证被用于关闭语义 Requirement

以下证据只能证明结构或身份：

- 文件存在；
- JSON Schema 合法；
- Hash 一致；
- Artifact 可安装；
- 接口可调用；
- 结果包含 30 项。

它们不能单独证明 30 条内容具有全概念差异，或真实发生了多路语义推理。

#### 3.3.4 实现与验证器可能共享同一错误假设

如果实现和 Lab 都认为“编号不同即唯一”，两者会一起 PASS。职责分离不等于判断逻辑独立。

#### 3.3.5 Linkage 的职责被过度解释

Linkage 证明：

```text
被构建、被测试、被认证、被安装的是同一个对象。
```

Linkage 不负责证明：

```text
这个对象生成的创意内容在语义上真正不同。
```

#### 3.3.6 Hash 保证不可替换，不保证内容正确

Hash 可以防止正确制品被替换，也会忠实锁定一个存在缺陷的制品。正确性必须来自有效 Oracle 和独立验证，而不是 Hash 本身。

### 2.4 现场证据回溯

#### 3.4.1 证据分层

| 证据层 | 状态 | 可支持的结论 | 不可支持的结论 |
|---|---|---|---|
| Factory Program/Requirement IR | `CURRENT_FACT` | 当前 Program 为 authoring-only；Requirement、Coverage 和 Candidate 已持久化 | 下游 Workpack 已执行或语义已合规 |
| v2.8 规范包 | `CURRENT_FACT` | 已定义独立 Lab、Runtime Receipt、挑战、进程谱系、负向/篡改和证据追溯原则 | 这些原则已被当前 IR/CLI 全部强制 |
| v0.2 Compiler/Validator 源码 | `CURRENT_FACT` | 实际算法、验证条件和自报字段 | 真实 Codex 语义执行曾发生 |
| v0.2 Matrix/C4/Certificate/Manifest | `HISTORICAL_FACT` | v0.2 wheel 曾在隔离环境测试、认证并安装回读 | 证书中的“distinct”一定代表全概念语义差异 |
| 两个 30 条 Portfolio | `HISTORICAL_FACT` + 本次只读重算 | 弱验证不变量与原始 Prompt 相似度可同时成立 | 对所有未来主题的统计结论 |
| v2.9 Schema/Gate/CLI | `V2_9_PROPOSAL` | 目标控制与验收方式 | 当前仓库已实现这些能力 |

#### 3.4.2 Requirement IR 回溯

冻结 IR 中有 18 个 Atom，18 条 `coverage_edges` 的 `owner_project_ids` 全部只指向 `MAIN_HARNESS_BUILD`。关键缺口如下：

| Finding ID | 现场事实 | 影响 |
|---|---|---|
| `TARGET_SEMANTIC_EXECUTOR_UNATOMIZED` | `target.primary_runtime` 提到 Codex semantic authoring executor，但 18 个 Atom 中没有一个 Atom 直接要求产品语义 Executor 或多路调用拓扑 | 目标描述无法生成 Atom 级 Runtime Proof |
| `SEMANTIC_REQUIREMENT_VERIFICATION_MODE_DOWNGRADED` | `ATOM-PORTFOLIO-002` 要求 30 条 holistic differentiation，`verification_mode` 却是 `SCHEMA_AND_COUNT_VALIDATION` | 语义要求可被数量与结构关闭 |
| `SEMANTIC_ATOM_LAB_ROUTE_ABSENT` | `ATOM-PORTFOLIO-002`、`ATOM-DIVERSITY-005`、`ATOM-EVAL-014` 均只路由至 `MB-G0/G0/MAIN_HARNESS_BUILD` | Lab 与 Certificate 没有 Atom 级关闭责任 |
| `NEGATIVE_CASE_DECLARED_WITHOUT_EXECUTABLE_ORACLE` | IR 已声明 paraphrase、duration-only 等负向案例，但未绑定 Oracle 实现、版本、阈值、输入 Artifact 和预期 Finding | 声明存在不等于矩阵实际执行 |

当前 Factory 状态仍是 `START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW`、`authoring_only=true`。Candidate 校验中的 `commands_executed=false` 与 `runtime_claims_verified=false` 是正确边界，不能把 Factory Candidate PASS 当作 Runtime 或 Conformance PASS。

#### 3.4.3 Compiler 与 Matrix 回溯

安装的 v0.2 `compiler.py` 是确定性本地编译器。源码中未发现 Codex/LLM/远端调用路径；候选由本地循环生成。关键闭环如下：

1. `_intent_charter` 通过关键词构造简单分类；
2. `_prompt_text` 将 brief、hard constraints 和 creative space 大段复制到每条 Prompt；
3. `_candidate` 写入唯一 `recipe-NN`，并直接输出 `semantic_atom_coverage.ratio=1.0`、`hard_gates_pass=true`、`portfolio_eligible=true`；
4. `compile_portfolio` 生成恰好 30 条，并把 `whole_concept_duplicates` 固定写为 `0`；
5. `validate_portfolio` 只验证数量、ID 和 12 轴 Genome 元组唯一；
6. v0.2 Certification Matrix 的 `PASS_30_COMPLETE_DISTINCT` 同样只要求 30 条、30 个 ID、30 个 Genome 元组、自报 hard gate 为真，以及资源 Hash 一致。

因此，Main 与认证矩阵不是共享同一个函数，却共享了同一个“Genome 元组唯一即可代表完整语义差异”的错误 Oracle 假设。

#### 3.4.4 原始 Portfolio 独立重算

对 `chinese_elder_memory_time_travel_20260724_001/portfolio.json` 的 30 条 `model_prompt` 进行只读重算：

| 指标 | 结果 | 解释 |
|---|---:|---|
| Candidate ID 唯一 | 30/30 | 结构唯一成立 |
| Genome 元组唯一 | 30/30 | 现有 Validator 会 PASS |
| 自报 `whole_concept_duplicates` | 0 | Producer 声明，不是独立重算 |
| 两两 5 字符 Jaccard 均值 | 0.6970 | 原始 Prompt 高度共享文本 |
| 所有 Prompt 共有的非空整行 | 5 行 | 固定块普遍存在 |
| 共有整行字符数 / 平均 Prompt 字符数 | 56.8% | 大部分成品由共同块占据 |
| `genome.scene` 原文进入对应 Prompt | 0/30 | Genome 声明与成品未建立充分可见绑定 |

第二个 `solo_summer_travel_vlog` Portfolio 也同时出现 30/30 Genome 唯一、自报重复为 0、5 个共有文本块、5 字符 Jaccard 均值 0.6021、`genome.scene` 进入 Prompt 为 0/30。该对照说明问题不是单一主题偶发。

这些指标不是“创意质量分数”，只用于证明：**结构唯一与自报 PASS 不能推出全概念语义差异**。

#### 3.4.5 发布链回溯结论

v0.2 发布链本身具有：

- `CERTIFICATION_MATRIX_RESULT.json`；
- `V0_2_C4_REPORT.json`；
- `V0_2_CONFORMANCE_CERTIFICATE.json`；
- `V0_2_INSTALLATION_RECEIPT.json`；
- `V0_2_ACTIVE_INSTANCE_MANIFEST.json`；
- `PASS_V0_2_ACTIVE_INSTANCE_MANIFEST_INDEPENDENT_READBACK_VALIDATION`。

所以发布链的身份连续性与安装回读不应被否定。应被否定的是从下列弱前提推出语义结论：

```text
30 unique IDs
+ 30 unique Genome tuples
+ producer hard_gates_pass=true
+ hashes and install origin match
= 30 holistically differentiated prompts
```

前三类结构/自报条件与后两类身份条件都可以为真，但结论仍不成立。


## 3. V-SCDSL Target Profile Canary

### 3.1 定位

本节后续测试全部属于 `VSCDSL_SEMANTIC_MULTILANE`，只验证该 Target Profile 能否复现并拒绝已知缺陷，不定义 Foundry 平台默认 Executor、Artifact、数量、Topology 或阈值。

### 3.2 V-SCDSL 正向测试

1. 模糊单人夏日旅行；
2. 世界杯主题；
3. 毕业季主题；
4. 三个不同怀旧时空主题；
5. 开门穿越世界各地；
6. 双人外卖员与保安详细故事；
7. 单图身份锁定；
8. 多图稳定角色映射；
9. 36 候选选出 30；
10. 二次补案只填被拒绝位置。

### 3.3 V-SCDSL 必须失败的负向测试

1. 只改变时长；
2. 只改变编号；
3. 固定 30 项模板轮转；
4. 同一故事换地点；
5. 近义词改写；
6. Input 主题没有进入 Prompt；
7. 多图角色交换；
8. URI-only 图片被声明 generation-ready；
9. 缺少真实 Codex 调用证据；
10. Fake Launcher 被用于认证；
11. Codex 模型绑定漂移；
12. Lane 数量不足；
13. 总调用超过 10；
14. JSX 被执行；
15. `unknown transition` 进入 Prompt；
16. 实现自报重复数为零但原始内容重复。

### 3.4 V-SCDSL 篡改测试

1. 修改 Invocation Receipt；
2. 修改模型或 reasoning 参数；
3. 删除某个 Lane 输出；
4. 替换知识 Chunk Hash；
5. 篡改 JSX Fingerprint；
6. 修改 Portfolio Selection；
7. 用另一个 Artifact 替换认证对象；
8. 修改 Release Metadata 而不重建 Artifact。


## 4. V-SCDSL Target Profile 验收

以下只关闭 `VSCDSL_SEMANTIC_MULTILANE` Canary，不构成平台默认规则：

1. 模板轮转、秒数变化、编号和 `recipe-NN` 伪唯一全部被拒绝；
2. 若冻结 Atom 明确要求 8-call baseline，则该拓扑可被独立回读；否则停在 Clarification，不得由平台臆造；
3. 单图简洁身份锁定和多图稳定映射通过；
4. Prompt、Genome、Codex、Seedance、Lane 数和相似度阈值全部来自该 Profile，而非平台 Schema 或 Gate 常量。


## 5. 回溯证据索引

为避免把路径存在、历史版本或聊天结论混为当前事实，本节登记本次只读复核的关键对象。为使文档本身可发布，证据只使用逻辑 Root Alias，不记录作者机器的绝对路径；本地物理映射属于不进入发行物的审计工作区配置。

```text
FACTORY = repo://harness-foundry-v2.8-chat-factory
TARGET = evidence://vscdsl/video-prompt-harness
BUILD_V01 = evidence://vscdsl/build-program/v0.1
BUILD_V02 = evidence://vscdsl/build-program/v0.2
```

| 证据对象 | 路径 | SHA-256 / 状态 |
|---|---|---|
| Frozen Requirement IR | `FACTORY/runs/PROGRAM-VSCDSL-VIDEO-PROMPT-HARNESS/requirement_ir/CURRENT_REQUIREMENT_IR.json` | `8f84c403d1056edd5dd0012e2431d3943ad1335454aa20a8825564bd2dfbbb24` |
| Factory Program | `PROGRAM-VSCDSL-VIDEO-PROMPT-HARNESS` | revision `30`; State Hash `d5108e5784fe3b7ff53954f0418e569938d8be400fdaf16b9565496427d9ccd8`; `authoring_only=true` |
| v2.8 Spec Lock | `repo://harness-foundry-v2.8-start-package` | verify PASS; aggregate hash `be81e6b46573abcbff0a9851812b3b2bb78814928e57a59d65a2b5bb733b8503` |
| Installed v0.2 Compiler | `TARGET/runtime/lib/python3.14/site-packages/vscdsl_harness/compiler.py` | `44d4d7e1fb8a7ceebb71cf47bccacb543661392114f778bee23b88fc3b2fdb29` |
| v0.2 Matrix Runner | `BUILD_V02/tools/run_v0_2_certification_matrix.py` | `ad34ca28d65619ca5474778be9129a530b628caf91c1d8de958a4cd0d620e792` |
| v0.2 Matrix Result | `BUILD_V02/execution/certification-matrix-20260723-001/CERTIFICATION_MATRIX_RESULT.json` | `612342f5a9c4498e87d290e8c695dfd1c12329130ac8ca1fbecc689ce4ed64bc` |
| v0.2 C4 | `BUILD_V02/execution/c4-report-20260723-001/V0_2_C4_REPORT.json` | `c82ac76c7a1e3263db656c1ccbe0ac7ac03a8131c20a2c7c5264731a8f5b9924` |
| v0.2 Certificate | `BUILD_V02/execution/conformance-certificate-20260723-001/V0_2_CONFORMANCE_CERTIFICATE.json` | `48759d5a97361b0914715428e623d97e803226d1159dc8d6bef40a285b29daa4` |
| v0.2 Active Manifest | `BUILD_V02/execution/active-instance-manifest-20260723-001/V0_2_ACTIVE_INSTANCE_MANIFEST.json` | `5a2b2fc95d62dd28fa6c2439873b12c93ba9d0c85c38ae6f9bf8e4dcfe6de2f7`; `REAL_TARGET_ACTIVE_V0_2` |
| Manifest 独立回读 | `BUILD_V02/execution/active-instance-manifest-20260723-001/V0_2_ACTIVE_INSTANCE_MANIFEST_INDEPENDENT_VALIDATION.json` | `ff54a57b9bfa15ceb367b262cfce29ed067616ae73896ab37d9986a3f7cf10fa`; PASS |
| 老人时空回忆 Portfolio | `BUILD_V01/execution/runs/chinese_elder_memory_time_travel_20260724_001/portfolio.json` | `4f3d9f8b0f3fcd6a130f79724b717aebfd8051e786c10a3a74281bea863fff4e` |
| 夏日旅行 Portfolio | `BUILD_V01/execution/runs/solo_summer_travel_vlog_20260724_001/portfolio.json` | `8420e41bff708ad1215b9d8cd706bef917c983fe5966b2bc745d95332be2ab2e` |

v2.8 规范回溯重点文件：

- `docs/06_agent_and_runtime_ownership.md`；
- `docs/07_intent_fidelity_and_traceability.md`；
- `docs/08_conformance_architecture.md`；
- `docs/11_acceptance_and_negative_tests.md`。

Portfolio 重算口径：

1. 对每条 `model_prompt` 去空白后构造字符 5-gram 集合；
2. 计算 30 条 Prompt 的 435 个两两 Jaccard；
3. 统计 30 条 Prompt 共同包含的非空整行及其字符数；
4. 以“共同整行字符数 / 平均 Prompt 字符数”计算共同块占比；
5. 检查每条 `genome.scene` 原文是否出现在对应 `model_prompt`；
6. 不采信 Producer 的 `status`、`evaluation` 或 `novelty_report` 作为重算输入。

本索引是回溯时点证据，不是 v2.9 Certificate；任何文件变化都必须重新计算 Hash 和结论。


## 6. 隐性规则与候选生产拓扑

### 6.1 当前问题的准确表述

V-SCDSL不是单纯“Prompt生成器”。它事实上需要从知识库、用户输入、图片事实、Target能力和创意经验中推断一套未完全显式化的生成规则，再据此构造Scene/Shot/Action/Camera/Edit/Audio和作品集差异。当前大量逻辑可能只存在于知识文档、Prompt措辞或Agent临场推理中，因此属于`IMPLICIT_PRODUCTION_LOGIC`。

这类问题不能只靠Diversity Validator解决。Validator可以拒绝同质结果，却不能告诉Producer应如何组合事实、Rule、创意维度和Target约束来产生更好的结果。

### 6.2 V-SCDSL Target Profile的候选生产拓扑

以下是需要由Architecture Design Round确认的候选，不是平台硬编码：

```text
Stage 0  Intake and Input Normalization
  Modules: input parser, media/reference registry, rights/scope facts

Stage 1  Evidence Grounding
  Subharness when multimodal/retrieval loop is required:
    source retrieval
    image fact extraction
    knowledge chunk binding
    fact/confidence ledger

Stage 2  Intent and Creative Brief Construction
  Semantic Decision Slot:
    theme interpretation
    explicit/non-goal extraction
    ambiguity and concept axes
  Output: CREATIVE_BRIEF_IR

Stage 3  Rule Selection and Concept Architecture
  Modules: rule resolver, target capability resolver, conflict resolver
  Optional Subharness: multi-hypothesis concept exploration
  Output: CONCEPT_ARCHITECTURE_SET

Stage 4  V-SCDSL Compilation
  Modules:
    Scene/Shot/Action/Camera/Edit/Audio compiler
    reference/identity binder
    prompt schema serializer
    Sidecar compiler

Stage 5  Portfolio Selection and Targeted Repair
  Modules: deterministic constraints, similarity metrics, slot tracker
  Semantic Decision Slot: whole-concept comparison
  Controller: only rejected slots may be regenerated

Stage 6  Package and Runtime Handoff
  Output: Prompt Bundle, Sidecar, lineage, applicable Rule/Capability bindings
```

这里Stage表达顺序；只有Evidence Grounding或Concept Exploration确实拥有局部状态、迭代检索/生成、专属工具和独立失败恢复时才成为Subharness。Identity Binder、JSX Static Parser、Schema Serializer和确定性相似度更适合作为Module。

### 6.3 隐性逻辑分类示例

| 当前隐性逻辑 | 正确分类 | 原因 |
|---|---|---|
| 多图角色不得交换或混合 | `DOMAIN_RULE`，关键时Hard | 定义输出业务正确性 |
| JSX只能静态解析、不得执行 | `GOVERNANCE_POLICY + MODULE_CONSTRAINT` | 涉及安全执行边界 |
| 模糊主题从多个创意维度展开 | `HEURISTIC` | 是生成策略，不应对所有Target硬编码 |
| 是否必须真实调用Codex/特定模型 | `TARGET_CAPABILITY / EXECUTOR_BINDING` | 由冻结Target Requirement决定 |
| 36候选择30 | `RUN_STRATEGY_PARAMETER` | 数量应来自Profile，不是平台Rule |
| Scene/Shot/Action/Camera/Edit/Audio结构 | `DOMAIN_GRAMMAR_RULE` | 定义V-SCDSL编译语法 |
| 单图保持人物可识别特征 | `DOMAIN_RULE` | 定义引用一致性 |
| 音频精确混音交给Sidecar | `TARGET_CAPABILITY + COMPILATION_RULE` | 由生成模型与后期能力边界决定 |
| 如何判断全概念差异 | `ORACLE_RULE` | 属于独立验收，不应控制Producer偷看答案 |

### 6.4 隐性规则显式化流程

```text
知识库/历史Prompt/失败样本
→ Rule Candidate Mining
→ Rule / Policy / Heuristic / Capability / Oracle分类
→ 来源、置信度、适用范围和冲突顺序登记
→ Expert Review与必要澄清
→ Target Profile Rule Bundle Freeze
→ Architecture Stage/Subharness/Module绑定
→ Runtime Decision Trace
→ 失败样本返回Rule或Architecture修复
```

Rule Candidate Mining属于归纳：从案例发现可能规则；Runtime消费冻结Rule属于演绎：只能按已确认规则运行。模型可以提出新Rule Candidate，但不得在本次运行中静默把它升级为Hard Rule。

### 6.5 v2.9应具备的“设计补全”能力

在不要求Factory完全自主设计的前提下，它至少应能：

- 根据输入列出缺失Capability、State、Decision Point和Failure Path；
- 为每项能力建议Stage/Subharness/Module/Semantic Slot，并解释理由；
- 识别Prompt或知识库中的隐性Rule/Policy/Heuristic；
- 提示Rule冲突、来源不明、Target能力未确认和工具绑定缺失；
- 生成1–3个生产架构候选及成本/漂移/恢复差异；
- 把用户的短回答更新为Architecture Decision，而不是只增加测试；
- 当问题改变Requirement语义时返回Reopen，不在Architecture层偷偷改需求；
- 生成Architecture Readback和Lock后再编译Workpack与Evidence Contract。

这使v2.9从“需求冻结器+证据校验器”扩展为“需求锁定后的受控架构设计助手+确定性运行合同编译器”。它仍不声称能替用户独立做出完整领域架构决策，但必须主动暴露缺口、提出候选、解释取舍并保持决策可追踪。


## 7. 非声明

本文件中的历史Matrix、Certificate、安装回读和只读重算，只说明来源案例在相应时点发生过什么，不证明Harness Foundry v2.9已经实现、迁移、发布或认证。案例Profile是否可执行仍需在独立v2.9 Program、状态库、输出根、Runtime、Oracle与授权链中重新物化和验证。
