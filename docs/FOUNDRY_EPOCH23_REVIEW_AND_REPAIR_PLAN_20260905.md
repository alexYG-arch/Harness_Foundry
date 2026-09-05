# Foundry epoch 23：研究复核与有界修复计划

日期：2026-09-05。状态：`REVIEW_AND_PLAN_ONLY / NOT_IMPLEMENTED`。

上行状态与下文执行记录保留为修复前基线；用户随后授权的实施进展另存于[修复执行记录](FOUNDRY_EPOCH23_REPAIR_EXECUTION_20260905.md)，不覆写原始发现。

## 1. 结论与审查边界

需要继续修 Foundry，但方向应从“逐条增加约束”改为“验证 Producer 生成合同的真实行为，并减少重复规则”。本次最明确的问题是集合元素绑定、条件分支适用性和悬空引用；它们无需攻击者，正常多素材或本地素材输入就能触发，具有跨项目通用性。

本次执行了资料检索、源代码与 epoch 23 Candidate 读取、内存中的合同探针，以及三个既有模块的 41 项单元测试。没有修复生产代码、编辑 Candidate、批准 Candidate、REOPEN、Freeze、Generate、创建 Execution Root，或执行目标 Workpack、Driver、Harness、TTS、Render。以下 Workpack 是 Foundry 源码修复计划，不是目标 Harness 的执行工作包。

审查集中于 Start Package compatibility 的 Producer → Schema/合同 → Validator → Oracle 接口，以及相邻的查询副作用。不是对 Foundry 41 项 core 能力进行完整动态认证。

基线：

- Program：`PROGRAM-GITHUB-SKILL-VIDEO-EXPLAINER-HARNESS-V1`；Candidate：该 Program 的 epoch 23 冻结输出。
- 当前 Git HEAD：`6f80bba482f9c3cd5760b995a27a7dc07081f462`，但工作树已有未提交修复，不能把 HEAD 单独当作本次被审代码的完整身份。
- 本次复核的持久化状态：revision 150，`CANDIDATE_READY_FOR_HUMAN_REVIEW`，event count 150。没有生命周期推进。
- 既有 source 修改与未跟踪文件均予保留；本次新增本文，不覆盖旧复盘或 preflight。
- 一个注意事项：现有 `status` 查询会重导出 `runs/` 的派生 JSON/JSONL。本次调用后发现该副作用，改用 SQLite `mode=ro` 复核状态。因此不能声称“除了本文没有任何文件写入”；能够确认的是没有 Candidate 编辑或权威状态推进。见 F08。

## 2. 文献与论坛如何改变方案

下列工程建议是结合本地证据作出的推论，不是论文直接评价 Foundry。论坛是经验线索，不是缺陷成立的证据或技术规范。

| 资料 | 可采纳的结论 | 对本项目的具体影响 |
|---|---|---|
| Barr 等，2015，[The Oracle Problem in Software Testing](https://discovery.ucl.ac.uk/id/eprint/1471263/) | 能执行测试不等于能判断结果正确；规范、模型、合同与变形关系是不同 Oracle 来源 | 独立预期不能全部由 Producer 输出反推；需要正常样例和真实反例 |
| Lopes 等，PLDI 2021，[Alive2: Bounded Translation Validation for LLVM](https://pldi21.sigplan.org/details/pldi-2021-papers/5/Alive2-Bounded-Translation-Validation-for-LLVM) | 有界翻译验证检查转换结果；资源边界也意味着可能漏报 | 验证每次 Requirement/合同投影是否保留语义；先用小型确定性模型，不引入完整 SMT 平台，不承诺零漏报 |
| Yang 等，PLDI 2011，[Finding and Understanding Bugs in C Compilers](https://web.stanford.edu/class/cs343/resources/finding-bugs-compilers.pdf) | 有意义、行为明确的输入配合差分测试能揭示编译错误；多个实现共同犯错仍可能漏检 | 比较独立的小型参考模型与实际生成合同，不把“新旧输出一致”当成唯一正确性标准 |
| [Hypothesis 官方 Stateful tests](https://hypothesis.readthedocs.io/en/latest/stateful.html) | 可生成操作序列；简单问题不必使用状态机 | 集合/分支先做表驱动测试；只对重试、续跑、失效传播使用小型状态模型 |
| Petrović 等，2021，[Practical Mutation Testing at Scale](https://homes.cs.washington.edu/~rjust/publ/practical_mutation_testing_tr_2021.pdf) | 无效或价值低的 mutant 会增加成本和脆弱测试；实践使用定向选择和抑制 | 不追求所有字段、所有 schema 实例都独立生成“只失败一条”的 mutation；先证明 mutation 的可满足性与价值 |
| [SLSA v1.2：Verifying artifacts](https://slsa.dev/spec/v1.2/verifying-artifacts) | digest、来源身份与预期参数是不同检查；递归依赖检查需按需取舍 | 保留字节边界和必要身份绑定，不把重复 hash 当作额外语义保证；不由此给个人项目引入签名基础设施 |
| [HN：What is property-based testing?](https://news.ycombinator.com/item?id=28586932)，讨论发表于 2021-09-19/20 | 有评论指出属性测试会复制实现或覆盖不真实边界，也有编译器实践者说明独立生成器的价值 | 属性应来自需求和可观察结果；把“生成器是否覆盖非首元素和条件分支”列入测试设计 |
| [Stryker Issue #1867](https://github.com/stryker-mutator/stryker-js/issues/1867)，2019 年历史问题 | 报告者观察到超时与高 mutation 分数同时出现 | 仅作为告警线索：Foundry 应区分预期拒绝、运行错误、超时和未执行，不以任意非零退出码作为反例成功 |
| [Stryker 官方结果状态](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/) | 工具明确区分 killed、timeout、runtime error 等；其分数规则有特定定义 | 不机械搬用工具 mutation 分数作为 Foundry 的逐 invariant 验收结论 |
| [Reddit：Mutation testing for E2E](https://www.reddit.com/r/softwaretesting/comments/1uy48hv/mutation_testing_for_e2e_mutate_the_assertion_not/) | 评论区区分“断言能变红”和“断言是否检查了正确层” | 辅助解释共同盲区；本文不采纳其插件，也不依赖帖子自报的效果数据 |

1998 年 translation validation 相关资料也被检索；部分 PDF 文本无法可靠解码，因此设计依据使用上述可读的 Alive2 会议原始摘要，不用乱码页面支持技术细节。

## 3. 重新裁定上一轮结论

应主动纠正过宽的判定，否则 Review 本身会成为新漂移来源。

- “126 处没有 `x-invariant-contracts`”不能直接等价为“126 个语义检查缺失”。聚合 receipt 已有 `x-ref-sha256-bindings` 和 `CASE_AGGREGATION_REF_SHA256_LINEAGE_V1` 路由；部分身份字段由 Schema const/oneOf、专门的身份派生合同处理。应检查等价执行入口与覆盖关系，而不是强制再复制一套 typed 合同。
- “166 个 AST 都不能运行”应收窄。166 是 Registry 中 evaluator/contract 条目数，其中 64 个声明为 `TYPED_KERNEL_V1`、102 个是外部专用算法。生成的嵌套 AST 与 Foundry 参考解释器接口不一致确实成立，但未来 `external_lab` 适配器尚未执行，不能断言全部真实运行必败。
- Acceptance/Negative 的调用并非整体丢失。`ACCEPTANCE_CASES.json` 有 6 个 Case，`NEGATIVE_CASES.json` 有 17 个；另有 779 个 Registry invocation 和 1 个公共 URL Case，共 803 个唯一预期结果引用。具体问题是两个消费方 fragment 指向不存在的 manifest 字段，见 F03。
- 不能按 `sha256` 文本出现次数衡量性能或过度设计。一个摘要在多个投影出现，不等于重复读取、计算了多次，更不等于都没有消费者。
- 个人本地目录物理权限漂移仍按冻结策略作为非阻塞诊断，不重新升级为阻塞项。

## 4. 问题清单与最小修复

### F01 · P1 · 已复现：FOR_ALL 重复检查第一个元素

位置：`semantic_contracts.py:652–693,1871–1891`；`invariant_contracts.py:789–805`；生成 Registry 的 `EVERY_MATERIALIZED_ASSET_REF_HASH_MATCHES_ASSET_SHA256`。

实际生成值：

```json
{
  "quantifier": "FOR_ALL",
  "subject_selector": "/assets/*/asset_sha256",
  "operand_refs": ["/assets/0/asset_sha256", "/assets/0/asset_ref"]
}
```

参考解释器会遍历 subject，但只替换 operand 中已有的 `*`，不会替换固定的 `0`。

本次用三个内存 asset、真实 `sha256(b'valid')` 与独立 bytes resolver 做单合同探针：

| 输入 | 应有结果 | 实际结果 |
|---|---|---|
| 三项均正确 | PASS | PASS |
| 仅第 1 项错误 | FAIL，定位第 1 项 | FAIL，但将三项全部标为失败 |
| 仅第 2 项错误 | FAIL，定位第 2 项 | PASS |
| 仅第 3 项错误 | FAIL，定位第 3 项 | PASS |

这是 Producer 生成合同与参考解释器组合后的可重复误判，不是目标视频执行结果，也没有证明整个完整 artifact 已通过所有 Oracle。

修复：明确区分 mutation seed、被量化 subject、相对当前 subject 的 operand、全局/依赖 operand。不能将所有数字路径一律换成通配符；全局固定索引可能合法。Validator 检查变量绑定和同一成员配对，而不是只检查 selector 含 `*`。

回归必须使用 Producer 真实生成的合同；同时保留手写独立预期。覆盖首/中/尾、嵌套两个数组、合法重排、等长错配及空集合的明确语义。

### F02 · P1 · 合同矛盾与局部探针已复现：分支不适用仍求值

位置：`semantic_contracts.py:617–642,3680–3885`；生成 ASSET_PLAN Schema。

Schema 的 SOURCE_EVIDENCE 分支要求 generation receipt、generation authorization、local build recipe 为 null。但是下面三个合同均为 `ANY_JSON_SCHEMA_VALID_BRANCH`，并且都只定位 `/assets/0`：

- `IMAGEGEN_RECEIPT_HASH_MATCHES_REFERENCED_BYTES_WHEN_MATERIALIZED`；
- `CODEX_IMAGEGEN_MATERIALIZATION_REQUIRES_SEPARATE_CURRENT_AUTHORIZATION`；
- `LOCAL_DETERMINISTIC_ASSET_RECIPE_AND_OUTPUT_ARE_HASH_BOUND`。

按 Schema 要求给这些字段 null，参考解释器分别返回 operand type mismatch、operand type mismatch、subject set empty，而不是分支不适用。这是正常 SOURCE 路径的合同冲突；不是为了通过校验而允许缺证据。

证据边界：探针只输入相关分支字段；本机两个已知 Python 环境均无 `jsonschema`，未安装依赖、未声称做过完整 Draft 2020-12 实例验证。

修复：在每个 asset 成员上执行 route/materialization 条件；适用成员必须验证，不适用成员显式 `NOT_APPLICABLE`。PLANNED 状态可以合法存在于计划，但不能当作完成 Render 所需素材。local recipe 的 implementation、input manifest、receipt、output 字节绑定应由明确配对列表覆盖，不能由 invariant 名字声称“全部”而只读取 implementation。

Motion 的 `ENTER_TIME_LESS_THAN_OR_EQUAL_TO_HOLD_START` 等仍有固定首对象与 wildcard 数组混用，应作为同一绑定修复族审查；不要把所有 SINGLE 都误判，全集合比较本来可以是 SINGLE。

### F03 · P1 · 静态确定：消费方引用了不存在的 Case manifest 字段

位置：`semantic_contracts.py:1610,1630`。

引用分别指向 `CASE_EXECUTION_MANIFEST.json#/acceptance_case_invocations/*/result_ref` 和 `#/negative_case_invocations/*/result_ref`，而生成 manifest 没有这两个键。Case 文件中已有实际调用信息，因此不应重新制造另一套独立调用事实。

修复：选定现有 Case catalog 或统一 invocation manifest 作为唯一事实源，消费方统一投影。增加“候选包资源 + fragment + wildcard + 值类型”的只读解析测试；不存在的 key 不得被当成合法空集合，不能仅验证 URI 字符串格式。

### F04 · P1 · 已复现接口不一致，实际 Lab 故障尚未证明

位置：`semantic_contracts.py:1879`；`invariant_contracts.py:35–47,721`；`validator.py:12878–12949`。

Producer 的嵌套 `predicate_ast` 使用 `operator`，Foundry 参考函数 `evaluate_predicate_ast_v1` 要求 `algorithm`。把生成 AST 原样传入，返回 `INVARIANT_CONTRACT_REQUIRED_FIELD_MISSING`。Validator 却校验外层完整合同，并检查内层与外层的字段投影相等，因此没有暴露消费接口不兼容。

修复：明确一个版本化、可执行的输入类型。选择统一字段或提供并测试唯一 adapter，不能依靠未来 Lab 自行猜测。64 个 typed 条目做生成对象到实际参考调用的 round-trip；外部专用算法走显式 dispatch/输入输出协议，不能因其不在七种 kernel operator 中而一律阻塞。

### F05 · P2 · 已发现声明缺口，先做有界证明再定阻塞范围

位置：`semantic_contracts.py::public_skill_job_interface`；`compiler.py:18113`；公共 URL result Schema。

- 动态 schema 模板绑定只有 13 个 atom 类型，未列出固定 Job 图中的 `NARRATION_SCRIPT`、`ASSET_BINDING_RECEIPT` 两个补充类型。需要确认动态派生规则是否负责补全，而不是仅数目对齐。
- `LAB-RUN-METAMORPHIC-CASE` 的 implementation entrypoint 是 source resolver，声明读域为 Candidate、写域为 cases，但 Case 预期包含动态视频、Media receipt 和 Job lease。缺少明确的完整 Job pipeline 委托/执行接口及资源读取合同。
- 三个 artifact descriptor 的 `producer_job_id` 可选，专门的字段级绑定未明确将 descriptor、`derived_job_id`、Media 中的视频与 lease 的 Job 关联。现有 decision_rule 声称 hash verified，不能据此证明动态身份 join 已实现。

修复前先用内存 source tree、临时 fixture artifacts 和 recording resolver 走一次“动态身份 → 依赖闭合 → lease → descriptor 消费”模型。stub 只提供测试数据，不能计为真实 TTS/视频或 Lab 完成。先看是否已有可复用的泛化派生逻辑，不复制第三套 DAG。

descriptor 作为通用内容描述符可以没有 Job；只在要求 same-Job 的消费上下文要求身份绑定，避免给共享资源强加伪 Job。

### F06 · P2 · mutation 可满足性风险，不能泛化为全部 Case 不可执行

位置：`semantic_contracts.py:506–554,2629–2633`。

默认 recipe 要求：base 全部 PASS、mutation 后 Schema PASS、恰好目标 invariant FAIL、所有其他 invariant PASS；部分策略仅给出改一个值或最多 4096 个候选的枚举规则。

例如改 asset 的 digest 同时影响叶子 byte lineage 和 canonical asset manifest。如果不重算非目标派生摘要，会出现多个合理失败。这个依赖是确定的，但本次没有运行完整外部 mutation solver，不能声称所有相关 recipe 都无解。

改进：区分独立反例、依赖闭包反例、Schema-native rejection。保持目标 invariant 必须失败；非目标派生字段可以按固定、审计可解释的配方重建，或声明预先确定的允许失败闭包。不得事后把“这次失败的所有项”填回允许列表。找不到反例应标为 `INCONCLUSIVE/CONTRACT_CONFLICT`，不是 PASS；只有适用性已确定不存在时才是 `NOT_APPLICABLE`。这些是建议状态，尚未修改冻结合同。

### F07 · P2 · 优化缺口：hash 诊断工具尚未形成产品级成本证据

`artifact_descriptors.py::audit_hash_projections` 已提供重复投影、无独立消费者、hash-of-hash 诊断，但当前 Compiler/Validator 没有调用它来审计实际 Candidate 投影。12 项 descriptor/audit 测试使用的是局部样例。

因此能说“诊断工具存在”，不能说“实际 Candidate 已完成 hash 去重或获得性能收益”。建议只读提取一次 descriptor/consumer/boundary 清单，加入非阻塞诊断；先测 digest 计算次数、读取字节量、耗时，再决定缓存或去重。不要新增一个必须逐 hash 人工审批的台账。

### F08 · P2 · 静态确定：只读查询夹带派生文件导出

位置：`service.py:232–250,3011–3065`。

`status()` 调用 `_export_program_views()`；后者 mkdir 并原子重写 FACTORY_STATE、SOURCE_REGISTRY、CURRENT_REQUIREMENT_IR、DECISIONS、READBACK、EVENTS 和已有验证报告。这不是 SQLite 业务状态推进，也不是 Candidate 覆写，但与用户对“只读审查”的直觉不符，并可造成只读挂载上的查询失败或审计噪声。

最小修复：让查询返回状态；导出放到明确的 export 操作或原有合法 mutation 后。测试应断言查询不调用 writer，而不是每次查询递归 hash 整棵目录。现有 CLI 消费者若依赖查询刷新视图，需要兼容说明；不为此新增一轮 Requirement freeze。

## 5. 为什么多轮修复后仍然出现问题

本次能直接观察到的原因，不是推测某一模型“不够聪明”：

1. 测试对象断开。`test_invariant_contracts.py` 的手写合同用 wildcard operand，能检出首/中/尾错误；Producer 输出却保留固定 `/0`。两个模块各自通过，组合后失败。
2. 部分独立 Validator 仍复制 Producer 的字段投影与分支白名单。没有 import Producer，不代表具有独立语义预期。
3. 修复覆盖“结构和引用存在”多于“正常路径可满足”。默认拒绝、nullable 分支、动态 Job 三者的组合缺少正向 witness。
4. 旧 golden 能防未经批准的输出变化，却也可能保存旧缺陷。必须同时维护“应保持的行为”和“已知坏输出应被拒绝”，不能简单更新 golden。
5. Review 本身有误报风险。不同合同表示、外部算法或未执行运行时不能因为不符合审查者偏好的格式而一律判 FAIL。

当前 `semantic_contracts.py` 7374 行、`validator.py` 25059 行说明维护范围已大，但行数不证明设计错误，也不构成全面重写的理由。优先抽离本次真正共享的绑定/协议边界，避免把所有历史代码重新翻修。

## 6. 最小架构调整

保留现有 Producer 架构，形成一条明确的可测试链：

```text
Requirement 中的行为约束
  → 类型明确的合同定义（一次定义；含量化变量、分支、操作数作用域）
  → Producer 生成 Schema/Registry/Case/Task 的投影
  → 独立检查投影与引用
  → 实际生成合同 + 独立正常样例/反例 → 小型参考解释器
```

“一次定义”是避免四处手写同一个字段规则；“独立测试”是不从待测输出生成期望答案，两者不矛盾。

正常路径与失败路径成对验证：SOURCE/LOCAL/授权 ImageGen/未授权计划、示例/真实 Demo、首/中/尾对象、固定/动态 Job。无需把所有维度做笛卡尔积；围绕实际共享字段和已发现依赖选取配对组合。

保留视频业务语义：一 Skill 一支约三分钟视频、本地开源 TTS、本地动画、逐对象声音画面同步、功能/场景/效果可追溯、目标 Skill 执行默认关闭。通用编译和引用绑定放 Foundry；音画阈值、讲解语义与素材效果属于视频 adapter 合同。hash 正确不能代替听感、事实真实性或效果判断。

## 7. Workpack 拆分与串并行

以下是待授权实施的源码修复单元；不实例化任何目标 Execution Workpack。

| 单元 | 范围和主要文件 | 前置 | 完成证据 |
|---|---|---|---|
| WP0：固定证据与 intentional delta | 新增独立回归 fixture/test；沿用既有 preflight/shadow/delta 方法 | 无 | F01/F03 确定反例；F02 分支 witness；旧错输出被明确标记，不被当作必须保持的正确结果 |
| WP1：合同绑定与调用协议 | `invariant_contracts.py`；`semantic_contracts.py` 的绑定/branch/AST 区域；对应 Validator 区域 | WP0 | F01/F02/F04 闭合；真实生成合同 round-trip；正例 PASS，首/中/尾反例定位正确 |
| WP2：Case 引用与动态 Job 消费 | Compiler 的 Case/public interface 区域；引用/descriptor 校验；独立测试文件 | WP0；接口集成依赖 WP1 | F03 无悬空 fragment；F05 有明确的动态 Job 依赖/读写/身份消费路径，或被实证降级 |
| WP3：有界 mutation 与分层验收 | mutation recipe、Case oracle binding、结果分类；独立 recipe 测试 | WP0；最终依赖 WP1/WP2 | F06 先复现或排除；目标失败可解释，超时/运行错误/不适用不冒充预期拒绝 |
| WP4：比例化诊断与纯查询 | `artifact_descriptors.py` 诊断入口；`service.py` 查询/导出；各自独立测试 | WP0 | F07 实际投影成本样本；F08 查询不调用 writer；无新增冻结字段或自动授权 |
| WP5：集成与反漂移验收 | Producer/Validator 端到端测试、现有 shadow/delta/测试索引 | WP1–WP4 | 历史反例、正常路径、合同组合全部闭合；全量命令通过；报告真实未覆盖范围 |

WP0 后，WP1、WP2 的独立测试准备及 WP4 可以并行；WP3 的反例可满足性分析也可并行。`semantic_contracts.py`、`compiler.py`、`validator.py` 的整文件集成由一个集成者串行落地，不能多方同时覆写。无需新建多个用户任务；若以后采用代理并行，需遵守当时的代理授权。

若 F05/F06 的有界复现被等价机制消除，关闭该具体假设并保存证据，不为了达到“所有怀疑都修过”的形式目标制造补丁。

## 8. 反漂移流程和结束标准

借鉴既有 `FOUNDRY_SEMANTIC_REPAIR_PREFLIGHT_RECEIPT_V1.yaml` 与用户提供的 shadow-fixture preflight，保留三件事：准确输入路由、应保持的行为、显式 intentional delta。该文档是方法参考，不是本次授权。

修复获准后连续推进：记录当前 HEAD + 现有 dirty 文件边界 → 先加入会失败的历史反例 → 修 Producer → 修对应 Validator/adapter → 同时运行正例与反例 → 集成回归 → 报告。内部分类、测试失败修正、文档更新不新增 Human Gate。

本轮结束标准：

- F01–F04 有独立预期、修复前失败和修复后通过的测试；F05/F06 有明确结论，不能留作“以后 runtime 再猜”。
- 合同绑定、nullable 分支、跨文件 fragment、same-Job descriptor、依赖失效各有生成合同的组合用例；不以字段个数或纯 golden equality 替代。
- 保持 AUTHORING_STOP、Candidate 不可变、根目录隔离、默认禁止目标执行，以及已有授权语义。
- 测试 fixture/模型不把自身标成真实媒体产物或已完成 Lab certification。
- 安装任何新测试依赖前先确定必要性；优先现有 unittest 与表驱动测试。完整 JSON Schema 集成若确有必要，作为明确开发依赖提出，不临时绕过校验。
- 实施后执行项目要求的全量测试；涉及工作流时再执行 spec/skill 验证：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/hffactory.py verify-spec --json
python3 tools/validate_skill.py
```

不以“又一次 Review 没想到新问题”作为结束标准，也不承诺以后没有新问题。报告应明确本轮覆盖的语义族、已知限制和未执行运行时。

修复完成后才提出下一次 Candidate 生命周期操作；epoch 23 的 REOPEN、新空 output root、Freeze 确认和 Generate 仍需用户独立明确授权，不能沿用旧授权。

## 9. 降低过度攻防与 hash 的具体边界

保留：源内容固定、最终产物字节绑定、冻结身份、必要的 same-Job 消费、根隔离、外部输入不自动执行、本地执行的副作用边界。

简化：

- 同一不可变字节对象、同一消费边界可复用 descriptor 和一次验证结果；可变输入不能只按路径永久缓存。
- 没有新信任/字节边界的摘要重复投影、digest-of-digest 先诊断再消除；实际冻结要求未 REOPEN 前不删除。
- 不为已有等价检查补同义 invariant；优先建立现有机制到行为约束的覆盖映射。
- 不把分布式发布/多项目攻防测试默认为个人本地流程新增门槛；保留现有 assurance profile 的适用性测试。
- Foundry 开发快速回归可以按语义族去重，仍覆盖每个 Job 的 specialization；不能偷偷减少已冻结 Candidate 的 803 个预期 Case 结果合同。
- 不做全项目无限 fuzz、所有字段 mutation、每个内部步骤 hash 与人工审批。针对已发现族执行有预算测试；无法判断就明确限制，而不是扩大防御链。

## 10. 本次执行记录

实际运行：

- `test_invariant_contracts.py`：13/13 PASS。
- `test_artifact_descriptors.py`：12/12 PASS。
- `test_assurance_profiles.py`：16/16 PASS。
- Producer 生成 asset hash 合同的首/中/尾探针：复现 F01。
- 生成 AST 原样交给参考解释器：复现 F04。
- Schema 声明的 null 分支字段交给对应 typed 合同：复现 F02 的局部不兼容。
- Case manifest 键、实际 Case 数量、公共 interface/descriptor 声明、查询源码：只读核对。

本次没有重跑全量 Foundry 测试、没有做完整 JSON Schema 实例验证，也没有运行目标媒体链路。41 项 PASS 只说明这些既有模块测试仍通过；它们与新探针的失败并存，正是本轮要修复的测试组合缺口。
