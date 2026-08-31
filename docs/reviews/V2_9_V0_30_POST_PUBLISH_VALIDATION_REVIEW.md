# v2.9 v0_30 发布后复核失败与 Epoch 31 修复

## 结论

v0_30 的 Candidate 字节没有被覆盖，失败发生在“发布事务完成后再次校验”的时序语义上。

生成前，Validation Report 与 detached Receipt 正确记录了不可变校验基点（validation basis）：Factory Event Store revision 232、tip `3915a4b3b15f3418c822a6effaea763c444db6922418b46f3ba974cd0cf04088`。生成成功后，权威事件库追加 Candidate 生成事件并推进到 revision 233、tip `69d49ed1771ecba795a30c4a71e0e93f7bc8ec7e79e0b3fb50e24c4ca291409b`。旧 Validator 把不可变 basis 当成必须永远等于可推进 current head 的值，因此刚发布就失败。

这不是“放宽 revision/tip 校验”。Epoch 31 改为验证三段关系：

1. basis 必须是当前权威事件链中的真实祖先；
2. 紧随 basis 的唯一 Factory Candidate 生成提交必须精确绑定 Candidate、Validation Report、detached Receipt、权威 Requirement IR 和 basis；
3. current head 可以继续前进，但必须通过同一条合法 Hash 链从该生成提交派生，不能分叉、伪造或重放。

## 术语通俗解释

- `validation basis`：生成前拍下的“验货时刻”。它必须保持不变，否则无法证明当时到底验了什么。
- `current Event Store head`：事件账本现在的最后一页。发布、审计等合法新事件会让它继续向后增长。
- `Candidate generation commit`：Factory 在账本中写下的“这批具体字节已经发布”记录。它把验货时刻与发布后的具体 Candidate 连起来。
- `detached receipt`：不嵌入自引用循环的外部收据，用 Hash 绑定报告字节和权威来源。

类比来说：basis 是装车前的验货单，generation commit 是货车出库章，current head 是仓库此后继续发生的流水。验货单不应被要求等于仓库最新流水，但必须能在账本中找到，而且出库章必须紧接验货单并写明这辆车、这批货和这张验货单。

## v0_30 只读证据

- Candidate：`candidate-v0_30`
- Candidate 文件数：331
- Candidate content SHA-256：`5ed10eed9ef9e32a09d6841e8561b827ae64cb53a2c8c5d972e8ba2768e2f60e`
- Validation Report SHA-256：`091f43e97216808f08b54a02f1fb1d4c1ca2f706d8c209ca215d16cc4090ed89`
- detached Receipt SHA-256：`3a8f90d68523d4d955a61beb57a0981eb5461ab31621ba8cfc92a4467c2cf832`
- 权威 Requirement IR SHA-256：`1cc0a8090d387b619e45bf1ff9a8539125841e249327ed6be7ef447c7e173e91`
- 生成基点：revision 232 / tip `3915a4b3b15f3418c822a6effaea763c444db6922418b46f3ba974cd0cf04088`
- 生成提交后：revision 233 / tip `69d49ed1771ecba795a30c4a71e0e93f7bc8ec7e79e0b3fb50e24c4ca291409b`
- 失败码：`VALIDATION_REPORT_AUTHORITY_BINDING_INVALID`
- Event Store Hash chain：PASS
- v0_30 Execution Root：不存在
- v0_30 Candidate：保留且未修改

机器可读证据见 `docs/reviews/V2_9_V0_30_POST_PUBLISH_VALIDATION_EVIDENCE.json`。

## Epoch 31 生产修复

- 公开 `validate_candidate` 不提供预发布绕过参数；缺少权威事件链时 fail-closed。
- 仅 Factory 编译器内部可调用受约束的 staging 校验；要求 staging 与目标同级、二者不同且目标尚不存在。
- Candidate 内分别记录标准化编译 IR Hash、portable IR Hash 和外部权威 Requirement IR Hash，避免把可移植投影误当成权威原文，同时不丢失精确绑定。
- Factory 生成事件的 snapshot 内保存非循环 `generation_commit_binding`，绑定 Candidate content Hash、文件数、Report Hash、Receipt Hash、Requirement IR Hash、basis revision/tip、生成 request 和 idempotency identity。
- 发布后复核直接读取完整 Factory Event Store 链，验证 basis 祖先关系、唯一直接子提交和 current head 后继链。

## 回归与对抗结果

- 发布前公开校验缺少生成提交：FAIL（`CANDIDATE_GENERATION_COMMIT_REQUIRED`）。
- 生成后立即复核：PASS。
- 后续合法事件：PASS。
- 伪造祖先：FAIL。
- 分叉 current tip：FAIL。
- 重放旧生成提交：FAIL。
- 同步重算 Candidate 内部 Hash、但无新权威提交：FAIL。
- Epoch 30 报告/收据既有测试：PASS。
- `tests.test_release_closure_candidate`：41/41 PASS。
- 全量单元测试：165/165 PASS。
- v2.8 Spec Lock：101 files，PASS。
- Factory authoring skill validation：PASS。

## 当前边界

Factory Program 已 REOPEN 到 Requirement Epoch 31。当前只完成生产代码、测试和证据提案；未创建 v0_31 Candidate，未创建 Execution Root，未消费 Human Gate，未启动 Driver/Workpack，未授予授权，未执行运行时动作。v0_31 仍须经过新的明确根绑定、Requirement Readback 和精确 Freeze 确认。
