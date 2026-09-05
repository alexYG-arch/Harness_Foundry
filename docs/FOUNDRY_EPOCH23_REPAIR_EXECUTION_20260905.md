# Foundry epoch 23 修复执行记录

日期：2026-09-05。状态：`SOURCE_REPAIR_AND_REGRESSION_PASS / AWAIT_EXPLICIT_REOPEN`。

执行依据：[研究复核与修复计划](FOUNDRY_EPOCH23_REVIEW_AND_REPAIR_PLAN_20260905.md)及随后用户“按计划自动推进修复”的授权。本文记录 Foundry 源码修复，不是 Candidate 批准、目标 Workpack 执行记录或媒体验收。

## 范围与保持项

- 保留此前未提交源码修改及未跟踪文件，没有覆盖旧 Review、preflight、shadow baseline 或用户输入。
- 没有编辑 epoch 23 Candidate、SQLite 权威记录或源快照；没有 REOPEN、Freeze、Generate、新建目标 Execution Root、启动目标 Workpack/Driver/Harness、下载模型、运行 TTS/Render、提交或推送 Git。
- 测试使用临时目录、内存模型和测试用字节；临时编译属于 Foundry 回归，不是对该 Program 重新 Generate。测试字节不冒充实际视频。
- 一 Skill 一支约三分钟视频、本地开源 TTS、本地动画、功能/场景/效果追溯、目标 Skill 执行默认关闭，以及已有授权和根隔离保持不变。
- 遵循比例化工程约束：没有新审批环、签名基础设施、第三套 DAG、全字段 fuzz、逐 hash 台账或目录递归摘要审计；没有安装新依赖。

## Intentional delta 与修复结果

| 单元 | 变更与证据 | 范围结论 |
|---|---|---|
| WP0 | 在真实 Producer 输出上先加入正常/反例；初始 6 项组合测试产生 15 个失败子断言，查询测试发现两次导出调用。后续嵌套 provenance 正例也先变红 | 修复的是已复现行为，不以更新 golden 代替正确性 |
| WP1 / F01、F02、F04 | 区分 SUBJECT/GLOBAL 操作数；同对象与 ref/hash 并行数组保持同一索引；按 materialization 分支求值；local recipe 检查四对字节；AST 使用解释器实际接受的 `algorithm` | 正常 SOURCE 路径不再要求无关 nullable receipt；首/中/尾错误可定位；空集合仍明确拒绝 |
| WP2 / F03 | Case result 指向现有 Case catalog；Fixture Job 集合指向现有 public interface 的 frozen fixtures；Negative variant 使用 `input_fixture/mutation_variants`。独立解析资源、fragment、wildcard，不将缺键吞成空集合 | 不新增重复索引；冻结输入重编译后的所有 Candidate operand 引用可解析 |
| WP2 / F05 | 公共 Case 入口改为完整 Job pipeline，resolver 作为首步骤；复用原 Producer 推导动态产物与传递依赖，返回单 Job lease 请求；same-Job 消费方要求 descriptor 的 producer_job_id，并核对视频/Media/lease 字节及身份 | 有界模型产生 24 个 Job artifacts，含 Narration、Asset Binding 与 12 阶段。模型不授予 lease、不执行 pipeline |
| WP3 / F06 | mutation 后仅重算受影响、非目标的 canonical 派生摘要，再检查 Schema 和所有 Oracle。Producer 产生 recipe，独立 Validator 核对；区分 timeout、runner error、schema rejection、目标未拒绝及 collateral failure | 保留“目标失败且其他 invariant 通过”；找不到反例不冒充成功。不声称已执行全部外部 mutation |
| WP4 / F07 | Candidate 公开验证响应可带有界非阻塞投影诊断；仅读取现有 Case manifest，报告诊断自身读取量、时间和 digest 次数；不将耗时诊断放入 prepublication 的冻结报告 | 这是实际投影样本，不是全产品 hash 成本分析或性能收益证明 |
| WP4 / F08 | status/readback 移除派生文件导出；CLI 用只读 store；合法 mutation 后的原有导出保持 | 查询不调用 writer，查询不存在的 Program 不创建目录/数据库 |
| WP5 | 增加 6 个回归文件、23 项测试；更新既有 resolver/AST 集成断言；执行全仓回归与 spec/skill/core 检查 | 416 项全仓测试及 23 项组合回归通过；不等于目标 Harness 认证 |

### 集成过程中提前发现的同族问题

1. ASSET_PLAN 已标准化时的提前返回绕过了 AST 重建，导致空白 schema 测试通过、冻结输入重编译失败。现在保留原 schema 形状，但仍重建 evaluator 投影；回归覆盖旧 `operator` 与固定索引输入。
2. provenance 的 ref/hash 是两个并行数组，不能只修同名数组内的路径。增加独立字节不同的嵌套正例及等长错配反例后修正位置绑定。
3. 严格 fragment 解析暴露 Fixture Job 来源集合错误和 Negative variant 层级错误；修消费方指针，没有放宽 resolver 的缺键规则。

这些不是再次增加对抗假设，而是将同一修复族放到正常输入、组合调用和重编译路径中验证。

## 回归索引

新增：

- `tests/test_generated_predicate_composition.py`：9 项；首/中/尾、nullable 路由、嵌套对象、旧 AST 重编译、并行 provenance、四对 local recipe 字节、重排和空集合。
- `tests/test_contract_references.py`：2 项；URI alias、fragment、合法空数组与缺键的区别。
- `tests/test_mutation_composition.py`：4 项；派生字段重算、失败分类、禁止修复 mutation 自身、Producer Registry 与独立 Validator 的组合。
- `tests/test_public_job_composition.py`：4 项；完整动态图、来源/工具/传递依赖读取、单 Job 写域请求、录制 resolver 读取、错 Job/字节/receipt。
- `tests/test_candidate_hash_diagnostics.py`：2 项；实际文档投影、诊断读取量、缺失可选输入不阻塞。
- `tests/test_readonly_factory_queries.py`：2 项；不导出、不创建不存在的 Program 数据库。

原有 66 项 `test_semantic_production_contracts.py` 在修复后独立运行通过。原有 assurance profile、根隔离、阶段证据和依赖回归没有删除或降级。

### 冻结输入的只读、内存重编译探针

使用 epoch 23 冻结 Requirement 输入；没有把重编译结果写回 Candidate 或 Program：

- 166 个唯一 kind/invariant 合同保持存在。
- 68 个 `TYPED_KERNEL_V1` 嵌套 AST 通过解释器入口合同校验；98 个明确为外部专用算法，没有假定它们可交给 typed kernel。
- Candidate operand 资源/fragment 解析失败数为 0。
- 完整动态 Job 参考投影为 24 个 artifacts，写域仅该 Job；lease 请求的 authorization_ref 为 null。

注意：68 是可调用输入协议验证数，不是 68 个真实 artifact 已运行通过的数量；独立行为用例由上述回归单独证明。

### hash 诊断的实测边界

只读抽取现有 epoch 23 `CASE_EXECUTION_MANIFEST.json`：1,230,057 bytes，4 个 paired digest 投影，3 个引用对象，1 组重复投影。该次诊断自行计算 digest 的次数为 0，单次耗时约 0.004 秒。

文档未投影 consumer 身份，因此诊断里的 `HASH_WITHOUT_INDEPENDENT_CONSUMER` 不能解释为“整个 Foundry 没有消费者”；它只是本次局部清单的信息不足。重复投影也不证明发生重复摘要计算。全 Factory digest 成本仍为 `NOT_MEASURED`，因此没有凭这个样本删 hash 或引入缓存。

## 最终验证

最终生产代码上的全仓命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

结果：416 tests，408.264 秒，OK，退出码 0。第一轮中间源码全仓结果为 412 tests / OK；不用它代替最终结果。公共 Job 模型用例随后增强到真实 artifact kind 和 Render 依赖断言，已单独通过；收尾时再次完整执行上述 6 个新测试模块，共 23 tests / OK。

已通过：

- 定向组合测试及 66 项语义生产回归。
- `python3 tools/hffactory.py verify-spec --json`：PASS，101 个文件，writes_performed=false。
- `python3 tools/validate_skill.py`：PASS，writes_performed=false。
- `python3 tools/hffactory.py validate-core --json`：PASS；41 项 capability、17 条 major failure path、26 个 selector result，0 findings，writes_performed=false。没有 external certification、release receipt 或 root 创建。
- `git diff --check`：通过。

Program 只读复核仍为 revision 150、150 个事件、`CANDIDATE_READY_FOR_HUMAN_REVIEW`；state_hash 与本轮计划基线一致。没有生命周期推进。

真实 CLI `status` 收尾复核退出码 0，返回相同 revision/state_hash；抽查的既有派生视图 mtime 未变化。它与两个纯查询回归共同说明本次查询没有依靠重新导出取得成功，而不是用递归 hash 审计来推断。

查询兼容性变化：`status` / `readback` 不再通过查询刷新派生文件。依赖这类副作用的调用方应使用查询返回的 JSON；原有合法 mutation 后的派生文件导出仍保留。没有为此新增授权或生命周期 gate。

## 已知边界与下一真实 gate

- 未安装完整 JSON Schema 验证依赖；本轮没有宣称做过所有正常 artifact 的 Draft 2020-12 实例 witness。
- 参考模型的输入前提是已由调用方解析并验证 source bytes；它不是网络 resolver、实际 Lab CLI、授权系统、TTS 或 renderer 的替代实现。
- 字节/身份绑定不证明视频质量、事实正确、TTS 听感、effect delta 的业务有效性；这些仍属于后续获授权运行时验收。
- 不承诺未来零缺陷。本轮通过标准是列明修复族的正反例、实际 Producer 组合及全量回归，而不是无限延长 Review。
- 源码修复完成不使 epoch 23 Candidate 自动升级。下一步仍需用户显式 REOPEN epoch 23 并绑定新的绝对空 output root；旧 Freeze/Generate 授权不沿用。
