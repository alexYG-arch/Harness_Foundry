# Foundry 2.9：epoch 26 后的算子族修复

日期：2026-09-06。范围：Foundry Producer、对应 Validator、参考解释器和源码回归。
状态：`SOURCE_REPAIR_AND_REGRESSION_PASS / AWAIT_EXPLICIT_REOPEN`。

不是 Candidate 批准、REOPEN、Generate、Workpack/Driver/Harness 执行、安装或认证。
没有更改 epoch 26 Candidate、Factory SQLite、2.8 来源或冻结 Requirement。
未提交、推送或修改发行版本。当前产品协议仍为 2.9，实现版本仍为 0.2.0。

## 修复依据与约束

延续既有 preflight / preservation shadow / intentional delta 方法；保留旧基线和旧报告，
不以更新 golden 消除已知错误。本次用独立行为预期以及完整 Schema 实例补充正确性依据。

2.8 标准链路是来源和构建过程，不是 2.9 全部业务语义的正确性证明。
本次不修改上游 2.8，也不把核心 41 能力 PASS 外推为视频 Harness 已验证。

## Intentional delta

| 单元 | Producer 修复 | 验证与边界 |
|---|---|---|
| 算子注册 | 将已有 163 个 invariant 的默认算法族明确注册；新增一个本地输出绑定规则。未知 ID 不再按 HASH、MATCHES 等子串猜测算法 | 原有外部专用算法仍是外部合同；注册不等于其行为全部已经本地实现 |
| 结构定义 | 移除 Producer 中重复的 arity/type 合法性表，使用 typed kernel 的统一签名验证 | 验证最终合并后的合同；中间草案不冒充最终输入 |
| 集合语义 | Claim、Narration、Motion 的唯一性读取完整集合；Motion 跨 shot/object/segment；唯一性算子进入本地 typed kernel | 独立测试首/中/尾、多个集合规模、重排、跨对象重复；空集合是否允许由 artifact Schema 决定 |
| 资产关系 | 新增 LOCAL_DETERMINISTIC_RECIPE_OUTPUT_REF_EQUALS_ASSET_REF，逐本地 asset 绑定 recipe output_ref 与 asset_ref | 复用原有两端字节校验来建立 digest 一致性，不新增摘要字段或额外 Hash 运算；SOURCE/未授权计划分支不适用 |
| Render 集合 | 相同 ref/digest 的重复对象行去重比较；同 ref 不同 digest 仍拒绝 | 完整 Asset Plan 正例包含多个对象复用同一素材；缺成员、字节冲突等原有拒绝保持 |
| 负例分类 | 独立反例要求仅目标失败；预先声明的依赖闭包反例要求目标失败且无闭包外失败 | 本地 output_ref 与 recipe 字节检查、observed curve 与完整 object binding 两条依赖被显式声明；不是观察到失败后生成允许列表 |
| 负例证据 | Registry 同时声明 required/allowed failure IDs；逐 Schema result 增加实际 failed_invariant_ids；物化分支固定 mutation seed 的适用状态 | 独立 Validator 检查规则、投影和分支。Schema-native 矩阵仍独立，Schema 拒绝不计作 invariant 证据；超时、未执行、runner error 不计 PASS |
| 重编译 | 从旧固定索引合同重建集合投影；已标准化 Asset Plan 补足输出关系；更新已知旧的 exact-one-failure 文案 | 正常编译和旧输入重编译均覆盖，重复编译应保持一致 |

## 回归与独立预期

新增 `tests/test_semantic_operator_families.py`，当前 16 项测试。
首批 9 项在生产修复前得到 7 failures、1 error、1 pass；新增依赖合同的两项测试也先因缺失能力失败。

关键行为证据：

- 使用真实 Producer 生成的 AST，不用手写替代 AST 冒充生成结果。
- 只改变 asset 的 ref/digest，recipe 四对字节仍各自真实；完整 Asset Plan Schema 合法，输出关系必须失败。
- 修改 recipe output_ref 但保留旧 digest，完整 Schema 合法；实际解释器观测到输出关系和 recipe 字节两项失败。
- 失败闭包不能被任意 caller 扩大；Registry 中省略、添加无关 peer 或删除 seed 分支会被独立校验拒绝。
- 独立 JSON Schema 验证会拒绝 LOCAL 分支下的 null recipe；此拒绝不能作为 invariant 负例成功。
- 逐 Schema 负例结果必须能够携带实际失败 ID 集，不再只靠一个笼统错误码表达关系。

测试输入是内存对象、测试字节及隔离测试 fixture，不是实际 Skill 输出、TTS、视频或外部 Lab 证据。
完整 Schema witness 覆盖本次 Asset Plan 组合及逐 Schema 负例结果；不声称全部媒体 artifact 均已生成真实 witness。

开发依赖新增 `.[test]`：jsonschema >=4.18,<5。本次安装在隔离临时虚拟环境；未安装目标工具。

## 冻结输入与整体验证

对当前 epoch 26 冻结输入进行只读内存重编译，不写回 Program 或 Candidate：

- 74 个 artifact；生产合同 findings 为 0。
- 逐 artifact 独立合同 findings 为 0。
- Oracle Registry 一致性 PASS；167 个 kind/invariant 负例合同。
- 重复编译结果一致。

最终验证（源码停止改动后运行）：

| 检查 | 实际结果 |
|---|---|
| 全仓 unittest discover | 462 tests，416.208 秒，OK；包含 16 项本轮新增回归 |
| verify-spec --json | PASS；101 个规范文件；writes_performed=false |
| validate_skill.py | PASS；writes_performed=false |
| validate-core --json | PASS；41 项核心能力、26 个精确测试 selector；未创建 Candidate 或 Execution Root |
| git diff --check | PASS |
| 正式 Program 只读状态检查 | revision=170，FROZEN，CANDIDATE_READY_FOR_HUMAN_REVIEW；与修复前一致 |

全仓命令为 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`，
Python 从本次隔离测试虚拟环境解析，具备 test/security 依赖。

保留中间失败记录：首轮全仓 462 项、396.070 秒，有 1 项报
`FACTORY_REQUIRED_IMPLEMENTATION_SOURCE_INVALID`，其余通过。首轮期间仍有源码收尾修改，
与该测试检测到的实现来源身份变化相符；这不是放宽校验的理由。
该路径原子性测试单独重跑 PASS（36.328 秒），随后停止源码改动，串行完成上表最终全仓回归。
最终结果采用完整重跑，不以单项重跑替代全仓验收。

上述 167 项是经过一致性检查的负例合同数量，不是已执行的 167 项外部 Lab 负例结果。
核心测试 PASS 也不代表视频 Harness、真实 TTS 或模型生成已执行。

## 可承诺与不可承诺

本轮关闭列明错误类别，补上相应的生成、验证、行为和再生成测试。其余外部算法的行为正确性不因注册表存在而自动成立。
此前声明的 12 阶段、逐 Job lease、公共 resolver、授权、字节证据和根隔离回归必须继续通过。
没有新增审批步骤、签名系统、第三套 Program DAG、递归目录摘要或全字段 Mutation 义务。

负例 Registry 的字段与 replay 规则有有意变更；旧 Candidate 不能混用新合同或新结果 schema。
正式重新生成仍须用户显式 REOPEN epoch 26、绑定新的绝对空 output root，再按原规则 Freeze/Generate。
