# Foundry 整体架构审查与语义族修复提案

日期：2026-09-06。状态：`REVIEW_AND_PLAN_ONLY / NOT_IMPLEMENTED / NOT_FROZEN`。

本次任务是文献、论坛研究与只读架构审查，不是源码修复授权。本文件只保存分析与建议；不替代 active proposal、Factory Requirement IR 或任何人类批准。没有修改 Producer、Validator、测试、Candidate 或 SQLite，没有 REOPEN、Freeze、Generate、执行 Workpack/Driver/Harness、安装或 Git 发布。

## 1. 结论

存在架构层面的缺口，但证据不支持推倒重写整个 Foundry。主要问题集中在可选 Start Package 路线的**语义定义 → 多制品投影 → 独立验收**这一层，以及围绕它的修复完成标准。

当前控制内核、状态隔离、来源绑定与原子发布应保留。需要改造的是：把靠多个 ID 表、字段名、mutation seed 和后置覆盖拼出的合同，逐族迁移为显式语义定义；再用真实生成合同与独立行为预期验证整个组合。单独补一个 `case_kind` 条件可以修当前实例，却不足以关闭反复出现的关系投影错误。

“彻底解决”的可操作含义是关闭已识别的**故障机制和逃逸路径**，不是保证今后零缺陷。没有证据支持用更多模型互审、更多 Hash、更多 Freeze 或全面形式化证明来替代这项工作。

## 2. 审查范围、基线和证据强度

- 当前源码 HEAD：`f4b2519f96ba85dc0106c6e62ff74b3eedb0b916`。检查前 tracked tree 干净；用户已有 `authoring_inputs/`、`authoring_requests/` 未动。
- 正式 Program：`PROGRAM-GITHUB-SKILL-VIDEO-EXPLAINER-HARNESS-V1`，epoch 27，revision 177，`FROZEN / CANDIDATE_READY_FOR_HUMAN_REVIEW`，批准仍为 `PENDING`。
- 本次重新执行 `verify-spec`：PASS，101 文件，`writes_performed=false`。重新读取 status/readback，未推进状态。
- Readback 保存的生成报告有 34 项静态 PASS，明确 `commands_executed=false`、`runtime_claims_verified=false`。这是持久化的生成报告，不冒充本次重新跑完整验证器。
- 本次直接读取当前 Candidate 的 74 个 artifact、167 个不同 `(artifact_kind, invariant_id)` 合同；71 个标为 `TYPED_KERNEL_V1`，96 个标为 `EXTERNAL_EXACT_ALGORITHM_V1`。分类数量不等于行为已验证数量；外部合同中也有本地参考实现，不能把 96 项全部称为未实现。
- 本次对 Case 集合进行只读复算，并调用 Factory 的纯合同检查函数；没有执行 Candidate 命令、782 个 Case、媒体链或外部 Lab。
- 上轮文档记录的 462 tests PASS 是已有回归证据，本次没有重跑全套，也不据此声称整个 Harness 可运行。

审查读取了架构/升级/import 文档、核心验证入口、semantic Producer、typed kernel、算子 catalog、对应 Validator、Assurance Profile、artifact descriptor、近期回归与 preflight/shadow/delta。它是跨层架构审查和针对性复现，不是对所有源码行或全部运行时组合的穷举认证。

## 3. 已确认的问题与不能混称为问题的事项

### A1 · P1 · 已复现：跨类别聚合域错误

位置：`src/harness_foundry_factory/semantic_contracts.py:1780`、`:1795`；Candidate 的 `canonical_sources/ARTIFACT_OBLIGATION_MANIFEST.json` 中 `FIXTURE_ACCEPTANCE_RECEIPT`。

两个合同分别检验 invariant 结果和 schema-native 结果，却使用同一个未分组 RHS：

```text
candidate://validation/CASE_EXECUTION_MANIFEST.json
  #/registry_case_invocations/*/result_ref
```

当前生成合同均为 `SINGLE`、`GLOBAL/GLOBAL`、`join_keys=[]`，没有 `case_kind` 过滤条件。

| 合法结果分区 | 应比较的引用数 | 当前 RHS 引用数 | 多要求的异类引用数 |
|---|---:|---:|---:|
| INVARIANT | 773 | 782 | 9 |
| SCHEMA_NATIVE | 9 | 782 | 773 |

这是完整集合的直接复算，不是推测：合法分区与全量集合不相等。纯 `_independent_invariant_contract_findings` 对该 Schema 返回 `[]`，说明该检查没有覆盖这条域约束。持久化生成报告也未阻止其发布。

结论：应正确通过的聚合被合同错误拒绝；是通用关系/分区语义问题，不是 TTS、视频风格或摘要计算问题。当前不能宣称正式外部 Lab 已经执行失败，因为没有运行它。

### A2 · 架构缺口：显式注册算法，不等于显式定义完整语义

当前算法族已不再按 invariant 名称猜测，这是有效改进。但其余字段仍由多个位置拼出：

- `_invariant_mutation_recipe`（`:534`）仍使用名称词项选择默认 mutation 策略。
- `_invariant_subject_selector`（`:733`）部分从 mutation target 把数字索引转换为 wildcard，再推导评估对象域。
- `_concrete_invariant_operand_refs`（`:756`）用 `_sha256/_ref` 字段命名推导对端。
- `_normalize_registered_operator_inputs`（`:830`）依据外部 ref/wildcard 等形状重写集合操作；另有具名规则覆盖 per-case 语义。
- `_bind_typed_predicate_fields`（`:874`）再次形成 scopes、types、cardinality 和执行分类。
- `semantic_operator_catalog.py:175` 的完整集合投影检查目前针对三项唯一性规则，另有一项本地输出绑定特例。

这些机制不意味着所有合同都是错的，也不意味着必须删除所有字典。问题是：**mutation 编辑位置、评估对象域、关系含义仍未完全分离为明确的输入合同**。修一个具名规则不会自动防止另一种同构投影错误。

### A3 · 验收架构缺口：一致性检查与行为正确性未完全连接

`validator.py:12930` 起的独立检查会验证字段、签名、分支和引用，并在 `:13035` 检查 AST 与外层字段投影一致。这些检查有价值，但两个表示共同携带同一错误时，一致性仍可 PASS。

上轮新测试已使用真实生成 AST，并具备多个对象和完整 Asset Plan Schema 正例，不能说“此前完全没有行为测试”。实际缺口是**尚未推广到全部相关语义族及其聚合消费边界**。A1 正是生成前没有被相应检查拦截的现证。

应区分三种独立性：

1. 定义共用：共享类型和算子签名，避免重复定义漂移，应该保留。
2. 检查实现独立：不调用 Producer 的构造/修复函数来检查其输出。
3. 预期语义独立：正例、反例和预期关系不能从待测输出复制得出。

只有第 2 项，或仅换文件/进程/模型，不足以证明第 3 项。

### A4 · 修复流程缺口：旧计划方向正确，但闭合单位仍偏向事故清单

`FOUNDRY_EPOCH23_REVIEW_AND_REPAIR_PLAN_20260905.md` 已明确提出完整生成合同、独立正例、组合用例、shadow/intentional delta。这些不是需要再发明的新原则。

现在再次出现 A1，说明应把“修复完成”从列明 Finding 的测试变绿，提升为受影响**语义族及消费链的可执行后置条件**。源码测试应先发现分组、跨 Job、分支、依赖与聚合之间的问题，再进入正式 epoch。

preflight 能确认读了哪些输入；shadow 能保护原有行为；delta 能解释有意变化。但这三者不能独立决定旧行为是不是正确。`test_semantic_repair_shadow_baseline_is_self_consistent` 对清单和 fingerprint 的测试属于元数据一致性，其绑定的行为测试有独立价值；不能把元数据自洽直接计为语义证明。

这不是要求取消 Freeze，而是避免让正式 Candidate Human Review 继续承担首轮语义集成测试。

### A5 · 结构性维护风险，不单独判为功能失败

当前 `compiler.py` 21,083 行、`validator.py` 25,274 行、`semantic_contracts.py` 7,684 行。大文件不是错误证据，但在这些文件中多次重建相同字段、域和关系，会增大修复影响面的判断成本。

模块拆分应随语义定义归位进行：先确定谁拥有定义、谁执行 lowering、谁独立验证，再移动代码。仅按行数拆文件，或者包一层新 facade，不能关闭 A1–A4。

### 应保留或诚实标为未验证的边界

- 核心 41 能力与可选 Candidate 路线已有明确区分；`core_validation.py` 将可选兼容能力标为 `NOT_RUN`。核心 PASS 不是本项目 Candidate 的语义证明，但这不构成核心能力本身失效的证据。
- 事务/CAS、独立 Program 状态、根隔离、原子发布、授权默认关闭没有被本次证据证明是 A1 的原因，不应搭车重写。
- `EVERY_INVARIANT_RESULT_COVERS_EXACT_APPLICABLE_SCHEMA_SHA256S` 已生成 `PER_CASE_SCHEMA_COVERAGE_V1` 和 `join_field=case_id`。不能仅查看早期 typed_specs 字面量，就误报它仍是全局集合比较；必须看最终生成合同。
- 真实本地 TTS、运动画面质量、Demo 效果和音画同步未执行。这些是未来运行时验收范围，不是通过更多静态 Hash 即可关闭的缺陷。
- 当前 hash 诊断只抽取一份 Case manifest：重复投影 1 项、未独立识别消费者 4 项、重复 digest 运算量 `NOT_MEASURED`。不能外推“整个 Foundry 做了多少无效 Hash”或据此大规模删除摘要。

## 4. “2.9 是由 2.8 标准链路生成的”如何影响结论

用户提供的标准链路背景与本地 import 记录相符：`V2_9_UPGRADE_MANIFEST.json` 绑定 v2.8 baseline commit、显式 worktree delta 和 78 项基线测试，并明确历史初始状态 `NOT_YET_IMPLEMENTED`。这个文件是导入边界记录，不是当前所有 2.9 功能的状态总表。

标准链路能证明来源、步骤和已声明约束被遵守，不能自动证明升级后的所有语义正确。如果输入定义漏了“分别按 case_kind 对账”，或者 Producer 与验证预期共享这一遗漏，标准链路会稳定重现它。

因此不能简单归因为“没有按标准流程做”，也不能要求先修 2.8 才能修当前问题。当前复现定位在 2.9 可选路线的实际生产代码；修复范围应从这里开始。只有发现上游规范自身错误且影响当前合同，才另行提出上游变更，不写只读 2.8 根。

## 5. 文献与论坛：采用什么，不采用什么

### 文献 / 官方技术资料

1. **Translation Validation，TACAS 1998。** 核心是针对每一次实际翻译，检查产出是否实现输入语义，而不是把信任只押在编译器历史测试上。对 Foundry 的推论：在已限定的合同语言内，验证 IR 到 Schema/Registry/Case 的实际投影关系。这里只借鉴方法，不声称有限样例等于论文中的形式化证明。阅读范围为出版社摘要。[原文页面](https://link.springer.com/chapter/10.1007/BFb0054170)

2. **The Oracle Problem in Software Testing，2015。** 自动产生输入与判断正确结果是两个问题；模型、规格、合同和变形关系是不同判断来源。对 Foundry：Case 数量不能替代正确预期；人的领域判断也有成本和局限。[作者机构页面](https://discovery.ucl.ac.uk/id/eprint/1471263/)

3. **Is the Cure Worse Than the Disease?，FSE 2015。** 研究将修复用测试与独立评估测试分开，观察到通过原测试的修复仍可能破坏未充分测试的功能。对 Foundry：加入未参与当前修复构造的保留评估集，不把全绿直接叫“根治”。该研究对象是当时的修复工具与小程序，不能把其统计结果直接套成 Codex/Foundry 的失败率。[作者版论文](https://people.cs.umass.edu/~brun/pubs/pubs/Smith15fse.pdf)

4. **Finding and Understanding Bugs in C Compilers，PLDI 2011。** Csmith 的重点是产生有明确语义的合法输入，探索组合，再做差分比较；无效/不确定输入会破坏判断。对 Foundry：先生成 Schema 合法、引用闭合、分支适用的正常模型，再变异；不以随机破坏文件触发的任何错误作为成功。[作者版论文](https://users.cs.utah.edu/~regehr/papers/pldi11-preprint.pdf)

5. **MLIR Operation Definition Specification。** 官方机制分层验证结构、类型、接口和更高层约束，后层可依赖前层已验证的事实。对 Foundry：复用现有 typed kernel，补明确的关系与域，安排分阶段 verifier；不建议为此引入 LLVM/MLIR 工具链。[官方文档](https://mlir.llvm.org/docs/DefiningDialects/Operations/)

6. **Property-Based Testing in Practice，ICSE 2024。** 对 Jane Street 30 位使用者的访谈支持复杂组件中的价值，也强调性质、合法数据生成器与效果评价的难点。对 Foundry：集中用于集合、分区、关联、顺序和依赖这些可精确定义的边界，不泛化为“全仓随机测就够了”。[作者版论文](https://harrisongoldste.in/papers/icse24-pbt-in-practice.pdf)

7. **Hypothesis 官方 stateful testing。** 通过动作序列与简化模型比较来检查状态关系；官方也说明简单问题未必需要状态机。对 Foundry：纯合同使用普通属性测试；只有续跑/幂等涉及动作顺序时使用状态模型，不建立第三套生产 Driver。[官方文档](https://hypothesis.readthedocs.io/en/latest/stateful.html)

8. **NIST 组合测试研究。** 配对能覆盖一部分交互，但不能保证覆盖更高阶故障。对 Foundry：根据真实共享字段、分支和依赖选择覆盖强度；低风险维度配对，已知耦合链显式增加三/四维组合，不全笛卡尔积，也不声称 pairwise 等于穷举。[NIST 资料](https://csrc.nist.gov/Projects/automated-combinatorial-testing-for-software/combinatorial-methods-in-testing/interactions-involved-in-software-failures)

### 论坛工程经验（非证明、非社区共识）

- HN 的 2024 讨论中，实践者强调简单模型对照，mutmut 作者讨论了限定关键模块的 mutation 成本，其他参与者指出过度 mock 和遗漏集成的风险。建议：纯逻辑广覆盖＋少量真实边界集成，mutation 只评估关键检查器，不把全仓 mutation 成为每次人工 Gate。[讨论](https://news.ycombinator.com/item?id=39850087)
- HN 的 2021 讨论中，有人报告性质测试可能复制实现复杂性；Common Lisp 测试实践者 pfdietz 描述了合法程序生成、差分与缩减，另有实践者描述用两个不同复杂度的解释器对照。建议：Oracle 采用更简单、来源独立的行为模型，不从 Producer 输出直接拷贝期望。论坛也提醒需求错误和第三方行为不是仅靠属性测试就能解决的。[讨论](https://news.ycombinator.com/item?id=28586932)

共同启示：不是缺少某一种神奇测试工具，而是需要“明确语义、合法输入、独立预期、实际投影、组合消费”同时成立。

## 6. 建议的架构目标：小型语义编译层，不再增加旁路

```text
已有 Requirement / 领域定义
  → 显式类型化语义定义
  → 引用、域、分支、关系解析
  → 已有依赖图与 Job 实例化
  → Schema / Registry / Case / Task 投影
  → 实际投影检查 + 独立正常模型/反例
  → 源码集成验收
  → 原有正式 Freeze / Generate / Human Review
```

### 6.1 将现有定义收拢为一个可执行定义源

沿用 `invariant_contracts.py`、`semantic_operator_catalog.py`，在这些边界内建立明确记录，不另造一个万能语言或新的 Program DAG。

每个适用规则明确以下语义；可复用现有字段，不要求一律新增字段：

| 维度 | 必须回答的问题 |
|---|---|
| domain / source | 哪个 artifact、哪类行、哪个 Job/Case/对象？ |
| selection / applicability | 是所有行，还是明确 discriminator 分区？ |
| projection / value type | 读哪一列/哪些列？字节、引用、数字、集合还是序列？ |
| quantification | 对整个集合一次判断，还是对每个对象分别判断？ |
| relation / join | equality、subset、membership、one-to-one 还是 per-key coverage？关联键是什么？ |
| collection semantics | 是否保序？是否允许重复？空集合是否适用？缺字段与合法空集如何区分？ |
| capability / evidence | 本地可评估、依赖显式 resolver，还是有版本协议的领域 evaluator？证明到哪一层？ |

mutation seed 只属于测试配方，不能成为生产评估对象域的隐含定义。`decision_rule` 用于可读解释，不补充机器合同中遗漏的过滤或关联。

以 A1 为例，正确语义是：先从 invocation 行选择 `case_kind=INVARIANT` 或 `SCHEMA_NATIVE`，再投影 result_ref 比较。结果引用唯一性、每个 Case 的 schema 覆盖和聚合分组是不同关系，不能合成一句含糊的“完整集合一致”。

定义可以共享，预期不能全部共用：结构/签名 checker 读取公共定义；独立行为测试另外构造两类行并明确预期分区。这样同时解决重复维护和共同错误未被发现的问题。

### 6.2 将外部解析能力与合同合法性分开

“本地检查不支持”不应自动等同于“外部精确算法合法”。当前已新增注册签名保护，应保留并扩展其分层含义：

1. 合同结构、类型、域必须先合法。
2. 如需外部资源，明确 resolver/输入范围，而非跳过关系验证。
3. 如需领域算法，明确版本、输入输出和适用边界。
4. `NOT_RUN/PLANNED` 不冒充执行 PASS，缺定义不包装成“以后 Lab 处理”。

不要求在 Candidate authoring 阶段实现和运行所有媒体算法；要求此阶段可以确定的关系语义不被无故推迟。

### 6.3 独立验证针对输出，不修复输出

- Validator 保持只读，不调用 Producer 的重建/正规化函数修好合同再验。
- 除 Schema/Registry 投影一致性，还验证过滤、关联键、对象域与所承诺关系一致。
- 对可本地解释的最终生成合同，跑独立小型正常模型和反例；必须证明“正确数据能通过”，不是只证明“坏数据会报错”。
- 外部算法的有限模型只能证明接口/关系或边界，结果应明确标识，不能冒充真实 TTS、渲染或 Lab。

### 6.4 边界归属与退役

保留：事务、CAS、发布、来源身份、现有依赖图、Assurance Profile、artifact descriptor 和有效 typed kernel。

迁移：同一语义族散落的 quantifier/selector/operand/branch/aggregation 定义，以及相应投影和校验。

退役：已迁移族中基于名称/索引形状猜语义的分支和重复映射；旧输入只经显式兼容 adapter 转换。每完成一个族就移除它的旧路径，不长期维护新旧两套同时生效的规则。

领域保留在 video adapter：3 分钟目标、本地开源 TTS、逐对象时序和运动、功能/场景/效果、示例与真实输出的区分。通用 Foundry 不内建某个 GitHub 仓库名或为某个视频补专有 validator。

## 7. 修复单元与执行顺序（提案，不创建执行 Workpack）

以下是源码工程单元。用户以后批准修复后，单元内部的诊断、测试和已授权代码修改可连续进行，不要求泛化“继续”或逐字段审批。正式 Program 生命周期仍遵循原有明确 Gate。

| 单元 | 工作与主要边界 | 前置 | 验收 / 退役条件 |
|---|---|---|---|
| E0 基线与故障族清单 | 沿用现有 preflight/shadow/delta；列出全部 167 个合同的语义族、消费者、可验证层级；将 A1 化为独立最小复现 | 无 | 清单无遗漏/重复；已修历史问题与当前失败分开；不只记录 Hash |
| E1 明确语义接口 | catalog + typed contract 定义；分离 domain、selection、relation、mutation seed；先覆盖集合/分区/关联族 | E0 | 两类分区、per-case join、非首对象、分支正例均有独立预期；无模糊 fallback |
| E2 Producer 族迁移 | 按 E1 改 semantic lowering，投影到 Schema/Registry/Case/Task；复用现有依赖图 | E1 | 整族全部调用方迁移；旧名称/索引推断路径退役；旧输入 adapter 有测试 |
| E3 独立检查器与模型 | 只读验证最终序列化输出；独立 relational oracle；正例、反例、变形、保留评估集 | E1；最终集成依赖 E2 | 能检出错误分区、丢过滤、丢 join、缺成员、跨 Job；不调用 Producer 生成预期 |
| E4 组合与外部协议 | Resolver → Job 图 → lease → descriptor → 聚合；mutation base 合法性；媒体协议与 NOT_RUN 边界 | E1；最终依赖 E2/E3 | 多 Job/多 Case 混合正例可满足；依赖错误、Schema 拒绝、runner 错误不计成功 |
| E5 集成与迁移后验收 | 在源码测试/隔离 fixture 中使用完整编译入口；全量回归、spec/skill/core；可移植兼容检查 | E2–E4 | 受影响族闭合，旧路径退役，未覆盖范围明确；然后才建议正式新 epoch |

可以并行准备：E1 接口确定后，E2 的生产迁移、E3 的独立测试准备和 E4 的边界样例准备。不能并行落地：共享 `semantic_contracts.py`、`compiler.py`、`validator.py` 的整文件集成；应由单一集成者串行合并。这里不请求或启动代理/新任务。

本方案与旧方案的关键差异不在 Workpack 名称，而在 E2/E5 的硬完成条件：**清点整族调用方、验证组合正例、删除旧推断路径、让正式生成入口消费该检查结果**。若只修 A1 两个 ID、添加两个测试而未满足这些条件，本方案不得标为完成。

## 8. 可执行验收设计

### 8.1 先建立正常模型，再建立失败模型

最低组合样例：两个 Job、两类 Case、每类多个 Case、每个 Case 不同数量的 Schema 实例；语义单位可以共享素材但不能错配归属。小模型仅使用测试数据和内存 resolver。

断言包括：

- 合法混合分区通过；添加另一类 Case 不改变本类的预期集合。
- 合法重排集合不改变结果；时间序列的重排必须按其有序语义处理。
- 删除本类一项必须失败；错分组、错 Job、错 schema 归属不能靠总数相等通过。
- 对象数量 1/2/多项以及首/中/尾错误均覆盖；合法空集与缺字段分开。
- 未适用分支可跳过；required 分支没有任何有效 witness 不能因空量化被计为覆盖。
- 内容重复与对象重复分别定义；共享 asset 不被误判为重复对象或跨 Job 泄漏。

这些性质必须作用于实际 Producer 最终输出。不能只测手写的理想 AST。

### 8.2 反例并非越多越好

- 区分 artifact mutation（证明某个合同能够拒绝错误数据）与 checker mutation（证明测试能发现错误检查器），两者不是同一种覆盖率。
- 独立反例和预声明依赖闭包反例分开；目标失败必须真实发生，不能看到多项失败后再扩允许名单。
- Schema 拒绝、NOT_RUN、timeout、runner error、不可构造反例，都不能计作 invariant 负例 PASS。
- mutation 无解时先检查冗余/蕴含关系、约束冲突或输入不适用；不要自动发明新算法或放宽 Validator。若需改变冻结需求才到人类 Gate。
- 只对关系解析/选择/关联/归属等关键核做有界 checker mutation；不对每个 hash 字段进行重复攻防。

### 8.3 用覆盖矩阵替代单一测试总数

E5 至少分别报告：

1. 合同定义覆盖：当前 167 项每项有明确责任域和验证层级，新增/删除列入 delta。
2. 可本地确定的通用语义族：每族有正常、错误、分支和消费组合的行为证据。
3. 74 个 artifact 的实际投影/依赖解析结果，不把“文件存在”计为行为 PASS。
4. 当前 A1 在修复前失败、修复后通过；错误旧输出仍被新 checker 拒绝。
5. 独立保留评估集：未参与当前实现构造的混合案例；一旦发现错误加入回归，并补新的评估案例，不把它当永久秘密答案库。
6. 未执行媒体/领域算法：明确 NOT_RUN，不因接口模型通过改写状态。
7. 工程全量测试、spec、skill、core 保持通过；兼容迁移若改变预期必须解释，而非批量更新 golden。

推荐优先用现有 unittest 表驱动建立确定性正常模型；只有样例规模/缩减需求证明有收益时，再加入 Hypothesis 测试依赖。快检查覆盖每次变更，耗时组合在集成节点运行；不每改一行就跑数百次全仓 mutation。

## 9. 降低过度防御与摘要负担

当前主要故障是功能正确性，而非攻击者绕过。计划保留精确授权、公共仓库不自动执行、Job 写域、必要源/产物身份和发布不可变性；不会为了简化而取消已有冻结要求。

建议减少：同一不可变字节跨投影反复描述、没有独立消费者的摘要、无新信任边界的 hash-of-hash、事故 ID 特判、重复否定用例、机器内部步骤上的人工授权。

具体原则：

- 一个明确字节域一个 descriptor，多处消费引用；对象身份和内容相同不是同一概念。
- 摘要证明字节一致，不证明语义、来源可信、模型真的运行或视频质量。
- 先量测实际重复读取/计算成本再缓存；不按 JSON 中 `sha256` 字符串出现次数判断性能。
- 通用属性与关系测试优先，受威胁模型影响的安全用例仍由现有 Assurance Profile 路由。
- 不新增签名网络、全目录递归摘要 Gate、多个认证项目、多个自动审查模型或新的泛用控制平台。

不通过修改 epoch 27 Candidate 删除任何字段；若最终兼容合同需要变更，由后续显式 REOPEN/Freeze/Generate 产生新包。

## 10. 修复后的停止条件与后续仍可能出现的问题

本次只交付提案。以后工程修复的停止条件是 E5 的可执行结果和退役清单，不是“Review 又没想到新问题”。确认这些结果后，才建议用户显式 REOPEN epoch 27 并绑定新的空 output root；旧授权不沿用。

仍可能发生的后续问题需要分层处理：

- 新的通用关系反例：扩展对应语义族模型，修生产定义/编译和检查器，不在 Candidate 打补丁。
- 外部工具、模型格式、环境变化：归领域 adapter/运行时兼容性验证，不回退成静态声明 PASS。
- 功能讲解是否真实、Demo 是否表达了效果、音画是否自然：需要源内容证据和真实媒体验收；不能由一般集合测试替代。
- 需求本身变化或歧义：明确提出差异再到真实 Human Gate，不偷偷把修复变成新产品要求。

本轮可以确认的是 A1 的具体矛盾和 A2–A4 的架构/验收缺口。其余风险是下一轮有界检查范围，不作为已经复现的阻塞 Finding，也不扩大本次授权。
