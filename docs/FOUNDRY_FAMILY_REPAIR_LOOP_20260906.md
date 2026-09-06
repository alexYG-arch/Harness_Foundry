# Foundry 语义族修复与复查执行计划

历史阶段记录：下述状态属于 epoch 27 之前的关系族修复，不代表当前整体完成。
后续 epoch 28 修复与未闭合范围见 [当前修复记录](FOUNDRY_EPOCH28_REPAIR_LOOP.md)。

状态：`SOURCE_ENGINEERING_ACCEPTANCE_PASS / WAITING_FOR_EXPLICIT_REOPEN`。用户已授权重新制定计划并循环修复/复查；本授权仅用于 Foundry 源码工程，不批准 Candidate 或执行目标 Harness。

## 顺序与完成单位

1. 清点当前 74 个 artifact / 167 个 kind-invariant 合同；区分通用可计算关系、领域算法和运行时证据，不以登记数冒充执行数。
2. 将集合/分区/逐 Case 关联这一整族迁移到明确的 collection query 定义；定义包含资源、行域、过滤、投影、分组和重复策略。移除该族从 mutation seed/索引形状推导语义的生产路径。
3. 生产与检查共用声明、但检查器不调用 Producer；用独立混合数据和朴素期望对实际生成合同做正常/失败/变形验证。
4. 循环复查：先检查生成输出和正常路径，再检查错误输入；发现可复现问题即补回归并修复根因。覆盖跨 Job、跨 Case、缺字段、空集、共享内容和分支，不增加无关攻防或摘要。
5. 从正式冻结输入只读重编译到内存，检查所有 artifact、Registry、公共 Job 专门化、依赖和合同重复编译；不发布新 Candidate。
6. 源码停止变动后运行全量 unittest、verify-spec、validate_skill、validate-core。若失败，修复后重新执行受影响检查及最终全量验收。

每轮记录“问题、复现、影响族、修复/排除、剩余范围”，不以 review 次数或测试总数作为唯一完成指标。正常模型不依赖待测合同来推导预期。

## 真实 Gate

源码修复不需要逐步人工授权。若涉及新增产品需求、旧规范修改或未知副作用则停止并说明；正式 REOPEN epoch 27、新空 output root、Freeze 确认、Generate 和 Candidate 审批仍是独立生命周期动作。不得自动提交确认 token，不直接编辑 epoch 27 Candidate。

“可进入 Harness 搭建”必须区分：源码问题闭合 → 新 Candidate 生成并审查 → 独立执行授权。源代码模型与静态验收不能冒充真实 TTS、视频或外部 Lab 结果。

## 复查记录

- Loop 0：重现两类 Case 结果共同对比 782 个全量 result_ref 的矛盾；开始集合/分区/关联族迁移。其余先保留现有行为，不借机全面重写控制面。
- Loop 1：初始 4 个回归先失败；修正分区后，再以未参与初次修复的关联样例复查，发现 Case 内 Schema/result_ref 对调、Job/source_id 对调仍可能通过。另发现旧 FOR_ALL 完整性检查不理解整体分组比较。新增 3 个失败回归后，用显式 group key/value tuple 修复，并将 Registry 完整性检查切换到同一定义。
- Loop 2：清点全部集合相等、数组并集、逐 Case 覆盖关系，迁移 23 个定义（24 个 kind-invariant 消费关系）。补全所有 query 读取列，包括分类键、关联键、投影列和 Job 身份；独立 Validator 校验读取域，正式静态生成入口解析对应 Candidate 列。删除这整族的旧名称/索引推导和早期算法映射，不保留两条并行生产路径。
- Loop 3：66 项语义集成测试暴露 8 个同源失败：无具体仓库的通用 Job Schema 未声明 job_id。修复 Producer，让已定义为 Job-scoped 的基础 Schema 就包含非空 job_id，仓库专门化只负责将值固定。此前 8 个失败不能被解释为 Validator 过严或直接跳过；已补无仓库 Schema 回归与有仓库/公共 Job 组合检查。
- Loop 4：复查新关联对负例的影响。Case 身份变异会同时破坏其结果/变体/Schema 归属；加入按 artifact kind 声明的依赖闭包与独立正常/变异样例。Alignment 和 Motion 共用 sentence invariant，但只有 Motion 有 shot-union 连带关系，不将两者允许集合混合。外部 Lab 的完整反例回放仍未声称完成。
- Loop 5：迁移适配器复查发现未知旧 branch_precondition 会被覆盖。已独立复现、增加先红后绿回归，改为拒绝无法识别的语义覆盖；明确旧输出可升级不等于任意输入可被静默重写。正在进行的第一次全量测试因此主动中止（不计 PASS），源码固定后重新全量运行。
- Loop 6：全量 481 项运行完毕，480 项通过；唯一失败是旧测试期待 CANONICAL 算子的 INVARIANT_OPERATOR_ARITY_INVALID。新关系算子已正确拒绝缺少操作数的合同，实际诊断为 COLLECTION_PROJECTION_INVALID。仅将该用例精确错误码更新为新语言的诊断，不放宽拒绝、不改 Validator；再次执行全量验收。
- Loop 7：上一步诊断码改动未覆盖旧 shadow 兼容约束：下一次全量仍是 480/481，唯一失败来自旧诊断码保护，不是错误合同获准通过。最终选择保留通用 INVARIANT_OPERATOR_ARITY_INVALID 诊断；新关系语言显式区分签名错误与域/投影错误，行为测试恢复原断言。未改写旧 shadow 基线、未新建摘要或用注释字符串绕过检查。随后一起复测行为、shadow 和最终全量。
- 最终专项：52 项关系族、typed kernel、历史语义族和公共 Job 组合测试通过；新文件有 19 个测试方法，多数为跨全部定义、多个位置/排列的表驱动测试。完整 Schema 合法正常样例通过，保持 Schema 合法的错绑样例被关系判据拒绝。

## 有意变化与未扩大的范围

- 新增一个有限的关系解释器 COLLECTION_RELATION_V1：domain、where、group_by、row_key、value_fields 和 same_job 显式；只处理已声明的标识集合关系，不是通用 SQL/执行引擎。
- 不新增 digest、hash-of-hash、签名、审批或状态机；不修改 Assurance Profile、物理权限策略、事务/CAS、原子发布或上游 v2.8 根。
- 所有 167 个合同已列入 [语义覆盖清点](FOUNDRY_SEMANTIC_COVERAGE_20260906.md)。74 个 artifact 的内存重编译、独立合同检查、Registry、组合图、幂等检查通过；公共 Job 专门化模型产出 24 个 artifact，授权仍为 null、执行为 false。
- 分类由 71 typed / 96 external 变为 93 typed / 74 external，是显式可计算关系进入参考解释器，不是新增 22 项真实运行时认证。其余算法不因接口模型通过而变成媒体/TTS/Lab 已执行。
- 正式 epoch 27 仍为 revision 177；旧 Candidate 不直接修补、不批准、不复用冻结或生成授权。本轮仅达到源码工程验收，后续正式 REOPEN/Freeze/Generate 必须保持原有独立授权。

## 最终验收命令

在项目依赖已具备的 Python 环境运行，无需安装新的测试库：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 tools/hffactory.py verify-spec --json
PYTHONDONTWRITEBYTECODE=1 python3 tools/validate_skill.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/hffactory.py validate-core --json
git diff --check
```

最终完整验收：**481 tests PASS，391.479 秒，0 failure / 0 error**（当前本地 Python 环境）。其中新增关系族测试 19 项；此前中止或失败的运行均不计 PASS。verify-spec（101 文件）、validate_skill、validate-core 及 git diff --check 全部通过。

全量完成后重新只读检查冻结输入：74 artifact / 167 kind-invariant 合同，独立合同与组合图 Finding 均为空，Registry 一致、重复编译一致、输入未改；公共 Job 模型仍为 DECLARE_ONLY_NOT_RUN、24 artifact、授权 null。

结论：本轮已识别并可复现的源码工程阻塞已闭合，允许建议进入新的正式 Candidate 流程；不宣称未来零缺陷、真实媒体/TTS/Lab 验收或 Harness 已建成。下一个真实 Gate 是用户显式 REOPEN epoch 27 并绑定新的绝对空 output root。没有批准旧 Candidate，没有创建正式 Execution Root，没有执行目标 Workpack/Driver/Harness，没有 Git 发布。
