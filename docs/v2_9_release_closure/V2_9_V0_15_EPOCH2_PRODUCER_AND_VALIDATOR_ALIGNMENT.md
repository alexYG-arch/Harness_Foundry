# v0.15 Epoch 2 生产器与双校验一致性修复提案

状态：PROPOSED_NOT_FROZEN_NOT_AUTHORIZATION

## 一句话结论

不能通过“让 standalone self-check 跳过旧文件”继续绑定 v0.15。真正问题是 Epoch 2 Requirement 已冻结，但 Epoch 2 生产实现还没有生成；必须先补生产器，再让 Factory Validator 和 standalone self-check 分别校验同一份 Epoch 2 产物。

## 当前发生了什么

v0.15 绑定前执行了三层检查：

1. Execution Project v0.7 自身边界检查：12/12 PASS。
2. Factory Validator：21/21 PASS。
3. Candidate standalone self-check：FAIL。

由于第3层失败，绑定器在创建 Execution Root 前停止。因此目前：

- Candidate v0.15 未修改；
- Execution Root v0.15 未创建；
- Human Gate 未消费；
- Registration Authorization 和 Parent Risk Envelope 均未授予；
- Driver、Workpack 均未启动。

## 根因的通俗解释

可以把 Candidate 想成一栋按“第二代设计图”报建的楼：

- 生产器只认识“第一代设计”和“普通兜底设计”，不认识第二代，于是按兜底设计出图；
- Factory Validator 看到不是第一代，就跳过第一代专项验收，但没有第二代验收，因此给出 PASS；
- standalone self-check 仍看到历史第一代要求，于是去找第一代设备，找不到便报错。

三方使用的“当前是哪一代”判定规则不同。更重要的是，第二代设备本身尚未生产。只修改验收规则会让缺失的设备被隐藏起来。

## 发现的生产缺口

冻结 Requirement 中已经包含 CORR-29-009 至 CORR-29-013，但 Candidate v0.15 中只有 canonical_sources/FROZEN_REQUIREMENT_IR.json 保存这些声明。没有找到对应的：

- Epoch 2 控制面 Manifest；
- 三层身份合同及实现；
- 通用恢复决策实现；
- Complexity Governor 与熔断实现；
- Product/Safety/Release 三条关闭通道实现；
- Evidence Index、Retention 与冲突投影实现；
- CORR-29-009～013 Coverage Matrix；
- 对应 Human Review Closure。

因此 v0.15 当前不是“只差一个自检条件”，而是“Requirement 已冻结、Producer 尚未完整编译”。

## 正确修复顺序

1. Producer：增加显式 Epoch Dispatch。Epoch 1、Epoch 2、未知组合必须有互斥且完整的处理；未知组合在发布 Candidate 前失败。
2. Epoch 2 实现：生成并 Hash 绑定身份、恢复、复杂度、三Lane关闭和证据投影的合同、Schema与运行模块。
3. Coverage：把 CORR-29-009～013 编译进独立 Coverage Matrix 和 Candidate Human Review Closure。
4. standalone self-check：独立验证 Epoch 2 产物，不再依据历史字段错误选择 Epoch 1 文件。
5. Factory Validator：独立验证同一规范，但不能调用 standalone self-check 作为自己的判断实现。
6. 原子发布门：Factory Validator 与 standalone self-check 任一失败，Candidate 都不得发布。
7. 对抗测试：缺文件、错Epoch、Hash一致语义篡改、旧Epoch重新取得Authority、两套Oracle分歧，均必须阻断。

## 为什么不能直接复用 v0.15 Human Gate

Human Gate 批准绑定的是 v0.15 的确定字节和语义。修复 Producer 后，v0.16 会有新的 Candidate Tree、实现文件和校验结果，因此必须重新Review并产生新的 Human Gate；旧批准不能平移。

## 本提案的停止边界

本文及配套 JSON 只记录修复范围，不执行 Factory REOPEN，不修改 Frozen Requirement IR，不生成 v0.16，不创建 Execution Root，不消费 Human Gate，不启动 Driver/Workpack，也不授予任何 Authorization。

下一步需要明确提交配套 Readback 中的 exact_later_reopen_request。
