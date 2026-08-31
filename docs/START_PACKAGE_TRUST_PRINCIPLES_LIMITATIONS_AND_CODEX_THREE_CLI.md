# Start Package 可信执行原则、架构风险与 Codex 三 CLI 独立性设计

> 本文合并上一份《Start Package 三工程架构详解、文献对照与优化评估》生成之后的全部讨论内容。  
> 内容范围：六条可信执行原则、六项架构风险，以及 Codex AI Coding 场景下三个不同 CLI 的独立性设计。  
> 本文只解释架构，不代表 v0.3 已经完成 Runtime Bootstrap、Driver 物化、Workpack 执行、认证或安装。

## 1. 总览

六条可信执行原则分别解决六种风险：

1. 功能成功不等于可信；
2. 送检对象可能被替换；
3. 准备环境不等于允许施工；
4. 验证方可能越权修改产品或历史；
5. 自动化可能失控；
6. 不同类型的失败可能被错误处理。

六项架构风险则提醒：

1. 自定义 Evidence 格式不利于外部互操作；
2. 只有 Hash 不能充分证明身份与授权；
3. 三个逻辑角色不一定形成真正独立的控制域；
4. Validator 自测通过不代表 Validator 一定正确；
5. Evidence 过多会降低可用性；
6. Main、Lab、Linkage 可能形成新的等待队列。

在 Codex AI Coding 中，三个不同 CLI 是形成独立性的基础，但只有配合独立权限、环境、身份、签名和不可变交接，才能成为真正可验证的三方控制域。

# 第一部分：六条可信执行原则

## 2. 把“产品能运行”和“产品可信”分开

### 2.1 “能运行”回答什么

“能运行”回答：

> 软件是否可以启动并完成某个功能？

例如，视频编辑插件能够：

- 读取时间线；
- 导入素材；
- 调用 FFmpeg；
- 导出视频；
- 返回成功退出码。

这些结果只能证明功能路径能够运行。

### 2.2 “可信”回答什么

“可信”回答：

- 它是否来自正确需求和源码；
- 构建过程中是否被替换；
- 是否在授权范围内运行；
- 使用的依赖和工具是否正确；
- 测试对象是否等于安装对象；
- 测试结果是否独立、完整并可复验；
- 是否覆盖失败、异常和篡改路径。

视频成功导出后，仍可能存在：

- 导出结果与时间线定义不一致；
- 使用了未经批准的 FFmpeg 版本；
- 写入授权目录之外的位置；
- 被测试的是开发版，被安装的却是另一个版本；
- 只测试成功路径，没有测试损坏素材和非法参数；
- 测试报告由插件自己生成，外部无法复验。

因此体系把判断分成三层：

```text
Main 自测：
产品能不能工作

Linkage：
被构建、测试、安装和认证的是不是同一个产品

External Lab：
这个产品是否真正达到规范
```

通俗类比：

> 汽车能发动，不等于它安全。还要确认送检车辆没有被调换，并由独立机构完成碰撞、制动和故障测试。

## 3. 把 Artifact 身份贯穿到安装和认证

### 3.1 Artifact 是什么

Artifact 是构建出来、准备交付或安装的对象，例如：

- Wheel；
- 压缩包；
- 二进制程序；
- 容器镜像；
- 安装包；
- 插件发行文件。

体系会为 Artifact 计算内容 Hash。Hash 可以理解为数字指纹：

```text
源码和构建输入
→ 构建 Artifact
→ Artifact Hash
→ 安装 Receipt
→ Installed Target Descriptor
→ Lab 测试结果
→ Conformance Certificate
```

### 3.2 为什么每一步都要引用同一个 Hash

例如：

```text
构建完成：
video-editor-plugin.whl
sha256 = ABC123

认证环境安装：
installed_artifact_sha256 = ABC123

Lab 测试：
tested_artifact_sha256 = ABC123

证书：
certified_artifact_sha256 = ABC123
```

只有全部一致，才能证明：

> 被构建、被安装、被测试和被认证的是同一个文件。

如果没有这条身份链，可能发生：

```text
A 版本通过测试
B 版本被安装
C 版本被写进证书
```

三个局部步骤可能都显示成功，但整体结论是假的。

通俗类比：

> 产品出厂时记录序列号；入库、送检、开箱和发证时都重新核对序列号，防止中途换货。

Hash 主要证明“内容是否相同”。更高级的版本还需要数字签名，证明“由谁构建、由谁批准、由谁检测”。

## 4. 不让 Bootstrap 自动获得执行授权

### 4.1 Bootstrap 是准备现场

Bootstrap 的作用是建立可信控制面，可以：

- 创建 execution root；
- 初始化 SQLite Event Store；
- 建立 Ledger 和 Evidence 目录；
- 注册 Start Package 和关键 Hash；
- 物化项目 Driver；
- 验证 Driver 能否正常读取 DAG。

Bootstrap 不能：

- 执行 Main、Lab 或 Linkage Workpack；
- 自动获得 A3 权限；
- 修改目标代码；
- 安装真实目标。

Bootstrap 完成后的正确状态是：

```text
Driver 已准备
Runtime 验证通过
执行模式 = A1_PLAN_ONLY
执行授权 = NOT_GRANTED
Workpack 执行数 = 0
```

### 4.2 为什么 Bootstrap 和 A3 必须分开

因为：

> 同意搭建控制台，不代表同意控制台开始执行所有工程任务。

通俗类比：

- Bootstrap Approval：允许施工队进场、搭脚手架、安装监控和登记人员；
- A3 Authorization：正式施工许可证，规定施工区域、任务、期限和预算。

如果 Bootstrap 自动获得执行权限，用户的一次初始化操作就可能意外触发大量 Workpack。

因此必须分成：

```text
Bootstrap 授权
→ 只建立可信控制面

A3 执行授权
→ 才允许 Driver 推进 Workpack
```

## 5. 不让 Lab 修改 Main，也不让 Linkage 修正历史

### 5.1 为什么 Lab 不能修改 Main

External Lab 是裁判，不是参赛者。

如果 Lab 发现 Main 输出错误，应生成 Finding：

```text
问题：
导出视频的音频时长与时间线不一致

Owner：
MAIN_HARNESS_BUILD

Return Path：
返回 MB-P2 或 MB-P3 修复
```

Lab 不能直接进入 Main 仓库修改代码，否则会导致：

- 裁判同时成为开发者；
- 修改没有经过 Main 的构建和评审；
- 原来的测试对象已经发生变化；
- Lab 可能修改实现来迁就自己的测试；
- 无法分清谁对最终结果负责。

正确流程是：

```text
Lab 发现问题
→ 输出 Finding
→ Main 负责修复
→ 生成新的 Artifact
→ Linkage 重新核对
→ Lab 重新检测
```

### 5.2 为什么 Linkage 不能修正历史

假设：

```text
证书引用 Hash = ABC123
实际安装 Hash = DEF456
```

Linkage 不能把证书里的 `ABC123` 改成 `DEF456`，因为这会伪造历史。

它只能报告：

```text
FAIL: ARTIFACT_HASH_MISMATCH
Owner: 安装或发布阶段
Return Path: 重新确认 Artifact 并重新安装、测试和认证
```

历史 Evidence 应保持不可变。修复后新增事件，而不是覆盖旧记录：

```text
事件 10：安装 Hash 不匹配，FAIL
事件 11：重新安装
事件 12：重新验证，PASS
```

通俗类比：

> 会计发现旧发票金额错误，不能拿橡皮擦改掉；必须保留原记录，再开更正记录。

## 6. 允许机器在 A3 预算内连续推进，但保留真正人工门禁

### 6.1 A3 是有围栏的自动驾驶

A3 不是无限自动运行，而是规定：

- 可以执行哪些 DAG Node；
- 可以执行哪些 Workpack；
- 可以调用哪些固定 Hash 的命令；
- 可以写入哪些目录；
- 使用哪个环境；
- 授权何时过期；
- 最多推进多少次；
- 最多进行多少轮修复；
- 最长运行多长时间。

示例：

```text
允许节点：
LAB_BOOTSTRAP、LAB_SELF_CONFORMANCE_PASS

允许 Workpack：
LAB-PROTOCOL、LAB-CLI、LAB-FIXTURES、LAB-SELFTEST

最大转换数：8
最大修复轮数：2
最长时间：1800 秒
真实目标安装：禁止
```

只要下一步仍在围栏内，Driver 可以自动连续执行：

```text
LAB-PROTOCOL
→ LAB-CLI
→ LAB-FIXTURES
→ LAB-SELFTEST
→ 到达下一人工门禁后停止
```

### 6.2 哪些情况必须停

- 真实目标安装；
- P3 被声明为 N/A；
- 扩大授权范围；
- 使用 waiver 跳过标准；
- Candidate 或 Command Hash 漂移；
- 非幂等命令结果未知；
- 状态无法唯一判断；
- 预算耗尽；
- 修复没有进展；
- 出现 A→B→A 振荡。

通俗类比：

> A3 像高速公路上的自动驾驶。车辆可以在指定路线、速度和里程内前进，但遇到收费站、道路封闭、路线改变或车辆异常时必须交还人工。

A3 减少的是没有判断价值的重复确认，不是取消人工控制。

## 7. 把 Acceptance Failure 与普通临时 Retry 分开

### 7.1 普通临时 Retry

Retry 适用于任务本身可能没有问题，只是环境暂时失败，例如：

- 网络短暂断开；
- Runner 暂时不可用；
- 临时文件锁冲突；
- 已确认没有副作用的传输超时。

只有满足以下条件才能自动重试：

1. 错误码在允许重试列表中；
2. 前一次副作用已经确认清理；
3. 命令具有幂等性，或能够安全恢复；
4. Retry 预算未耗尽。

示例：

```text
上传测试 Fixture 时网络断开
→ 确认目标端没有残留半文件
→ 自动重试一次
```

### 7.2 Acceptance Failure

Acceptance Failure 表示命令已经完成，但结果不符合验收要求，例如：

- 视频成功导出，但分辨率错误；
- ASR 成功返回，但时间戳错位；
- 插件成功安装，但来源 Hash 不匹配；
- 命令退出码为 0，但必需 Evidence 缺失；
- Artifact 构建成功，但负向用例没有被拒绝。

正确流程是：

```text
Acceptance FAIL
→ 创建 Finding
→ 确定 Owner
→ 进入 Repair Attempt
→ 执行有限修复
→ 重新验证
→ 独立 Review
→ PASS 后才能 Promotion
```

如果把 Acceptance Failure 当作普通 Retry，可能出现：

```text
结果错误
→ 重试
→ 结果仍错误
→ 再重试
→ 偶然一次输出不同
→ 被错误标记为 PASS
```

### 7.3 结果未知

还有一种更危险的状态：

```text
命令已经开始
但 Runtime 崩溃
无法确认命令是否完成
且命令不是幂等的
```

例如真实安装执行到一半，Runtime 中断。

这时既不能 Retry，也不能直接判定失败，必须 Hard Stop：

```text
UNKNOWN_NON_IDEMPOTENT_OUTCOME
```

等待人工确认真实外部状态。

## 8. 六条原则的组合逻辑

```text
Main 把产品做出来
→ 但不能自己宣布可信

Artifact 获得固定身份
→ 从构建一直跟踪到安装和认证

Bootstrap 建立控制现场
→ 但不自动获得施工许可证

Lab 独立判断质量
→ 发现问题只能交给 Main 修

Linkage 检查证据关系
→ 发现历史错误不能直接篡改

A3 在明确围栏内自动推进
→ 到真正风险决策处交还人工

临时环境问题可以重试
→ 产品不合格必须形成 Finding 并修复
```

目标不是设置更多门禁，而是：

> 能自动判断的事情由机器连续完成；涉及身份、授权、风险和不可逆影响的事情，由人作出明确决定。

# 第二部分：六项架构风险

## 9. 格式自定义：外部工具难以直接消费 Evidence

### 9.1 什么叫格式自定义

体系会产生大量自定义 JSON：

```text
WORKPACK_RESULT.json
PROGRAM_DRIVER_STATE.json
PHASE_TRANSITION_LEDGER.jsonl
EXECUTION_AUTHORIZATION.json
Finding
Receipt
Readback
Evidence Index
```

这些文件对 Harness Foundry 自己是清晰的，但 GitHub、CI 平台、安全扫描器、制品仓库或第三方审计系统未必认识这些字段。

例如内部 Finding：

```json
{
  "finding_code": "ARTIFACT_HASH_MISMATCH",
  "owner_project": "MAIN_HARNESS_BUILD",
  "return_node": "MB-P4"
}
```

外部平台可能只认识：

- SARIF；
- in-toto Attestation；
- SLSA Provenance；
- SPDX；
- CycloneDX；
- OpenTelemetry。

### 9.2 通俗类比

> 公司内部使用一套自创插头。公司自己的设备可以连接，但拿到外部市场后，所有设备都需要转接头。

转接头越多，越容易：

- 字段丢失；
- 状态翻译错误；
- 同一概念有多个名称；
- 版本升级后不兼容；
- 外部审计无法自动验证。

### 9.3 优化方向

把内部运行格式与外部证据格式分开：

```text
SQLite / 内部 Event Model
→ 标准 Evidence Adapter
→ SLSA / in-toto / SPDX / SARIF
```

推荐映射：

- Artifact 构建来源：SLSA Provenance；
- 供应链步骤：in-toto Attestation；
- 签名封装：DSSE；
- 软件组成：SPDX 或 CycloneDX；
- 安全 Finding：SARIF；
- 运行 Trace：OpenTelemetry。

内部格式可以保留，但关键证据应能够无损导出。

## 10. 只有 Hash、缺少签名

### 10.1 Hash 能证明什么

Hash 可以回答：

> 这个文件现在和之前是不是同一份内容？

文件变化后，重新计算的 Hash 通常会不同。

### 10.2 Hash 不能证明什么

Hash 不能回答：

- 谁生成了文件；
- 谁批准了文件；
- 是否由可信 Runner 构建；
- Hash 在什么时候产生；
- 谁把 Hash 写进报告；
- 报告中的 Hash 是否也被攻击者重新计算。

攻击者可能同时替换 Artifact 和记录 Hash 的 JSON：

```text
原文件 Hash = ABC123
恶意文件 Hash = DEF456
```

然后把报告改成：

```json
{
  "artifact_sha256": "DEF456"
}
```

文件与报告仍然一致，但身份和授权已经丢失。

### 10.3 通俗类比

- Hash 像商品序列号；
- 数字签名像制造商盖章；
- 时间戳像公证时间；
- 透明日志像公开登记簿。

只有序列号，没有制造商签章，攻击者可以换货后重新贴一个新序列号。

### 10.4 优化方向

重要 Evidence 应包含：

- 签名者身份；
- 签名算法；
- 签名时间；
- 授权上下文；
- 证书或公钥引用；
- 透明日志证明；
- 签名撤销状态。

优先签名：

- Requirement Freeze；
- Execution Authorization；
- Workpack Result；
- Artifact Provenance；
- Installed Target Descriptor；
- Lab Result；
- Conformance Certificate。

## 11. 逻辑独立不等于组织独立

### 11.1 什么是逻辑独立

体系将角色拆为：

```text
MAIN_HARNESS_BUILD
EXTERNAL_CONFORMANCE_LAB
CONFORMANCE_LINKAGE_REVIEW
```

并规定：

- Main 不能发证；
- Lab 不能修改 Main；
- Linkage 只能只读检查。

这是逻辑职责分离。

### 11.2 为什么可能只是名义独立

如果三个工程由以下条件运行：

```text
同一个人
同一台电脑
同一个管理员账户
同一个 Git 权限
同一个 Runtime 进程
同一套密钥
```

同一控制主体仍然可能：

1. 修改 Main；
2. 修改 Lab Validator；
3. 修改 Linkage 规则；
4. 重写 Evidence；
5. 重新计算 Hash；
6. 最后输出 PASS。

通俗类比：

> 一个人戴三顶帽子，上午是施工队，下午是质检员，晚上又成为认证机构。

### 11.3 独立性分层

#### L0：逻辑独立

```text
不同模块和角色
同一人、同一权限
```

#### L1：权限独立

```text
不同账户
不同写权限
Lab 无权修改 Main
Linkage 只有只读权限
```

#### L2：环境独立

```text
不同 Runner
不同密钥
不同存储权限
独立认证环境
```

#### L3：管理独立

```text
不同负责人或团队
验证预算和排期不受 Main 控制
```

#### L4：外部独立

```text
第三方机构
独立基础设施
独立法律或合同责任
```

证书应声明实际达到的独立性等级，而不是笼统声称“独立验证通过”。

## 12. 验证器自测悖论

### 12.1 问题是什么

External Lab 会有：

```text
LAB-CLI
LAB-FIXTURES
LAB-SELFTEST
```

Lab 可以证明：

```text
Lab CLI 通过了 Lab 自己编写的 Fixture
```

但这不能证明 Lab CLI 一定正确，因为：

- Validator 与测试可能基于同一个错误理解；
- 正确结果和预期结果可能一起写错；
- Fixture 未覆盖真正危险的情况；
- Validator 只能识别作者想到的攻击；
- Selftest 可能绕过生产运行路径。

### 12.2 通俗类比

> 一把尺子用自己来测量自己，最后得到“长度完全正确”。

如果尺子的刻度从一开始就是错的，它仍然可能通过自己的检查。

### 12.3 具体例子

规范要求：

```text
视频音频时长与时间线误差不得超过 100 毫秒
```

Lab 开发者却错误理解为允许相差 10 秒。

于是：

- Validator 按 10 秒容差编写；
- Fixture 按 10 秒容差编写；
- Selftest 全部通过；
- 实际规范仍然被违反。

### 12.4 如何验证 Validator

#### Golden Corpus

建立经过人工、标准或外部专家确认的固定样本：

```text
应 PASS 的样本
应 FAIL 的样本
边界样本
历史缺陷样本
恶意篡改样本
```

#### Mutation Testing

故意注入错误：

- 修改 Artifact Hash；
- 删除必需 Evidence；
- 伪造 Runner Identity；
- 替换安装来源；
- 调整视频时长；
- 修改 Program ID。

如果 Validator 没有发现，说明能力存在缺口。

#### Differential Testing

使用两套独立实现：

```text
Validator A 输出 PASS
Validator B 输出 FAIL
→ 必须进入人工调查
```

#### 外部验证

由第三方工具、独立专家或外部实验室抽查 Lab。

这相当于：

> 不只检查产品，还要定期校准检测仪器。

## 13. Evidence 爆炸

### 13.1 什么叫 Evidence 爆炸

每个节点可能记录：

- 输入 Hash；
- 状态 Hash；
- Authorization Hash；
- Command Manifest Hash；
- stdout/stderr；
- Receipt；
- Readback；
- Postflight；
- Review；
- Finding；
- Repair Result；
- Promotion Event；
- Ledger Event；
- 时间戳；
- 环境信息。

如果有 100 个 Workpack，每个产生几十份记录，最终可能出现数千个文件。

### 13.2 为什么证据多不一定更可信

- 人无法读完；
- 真正异常被淹没；
- 同一信息被重复记录；
- 多个读视图可能不一致；
- 存储和 Hash 校验耗时增加；
- 用户不知道哪个报告是最终结论；
- 修复一个节点会使大量 Evidence 失效；
- 审计人员最终仍然只能抽样。

通俗类比：

> 一宗案件有十万页材料，却没有目录、摘要和关键证据索引。材料越多，反而越难判断真相。

### 13.3 优化方向

建立证据分层：

```text
L0：用户结论
L1：门禁和 Finding 摘要
L2：Workpack Result 和关键 Receipt
L3：完整 Event、日志和底层 Evidence
```

同时：

- SQLite 作为单一权威状态；
- JSON/JSONL 作为可重建读视图；
- 相同 Evidence 通过 Hash 引用，避免重复复制；
- 建立 Evidence Index；
- 默认只显示结论、关键证据、失败原因、Owner 和 Return Path。

## 14. 工具发布队列

### 14.1 为什么会出现队列

当前顺序大致是：

```text
先构建 Lab 工具
→ 再构建 Linkage 工具
→ 再构建 Main
→ Main 变更后重新 Linkage
→ 再进入 Lab
```

如果 Main 的每个小改动都要等待：

1. Linkage 人员；
2. Lab 人员；
3. 人工审批；
4. 完整回归；
5. 工具重新发布；

三个工程就会形成三个排队队列。

通俗类比：

> 每改一个按钮颜色，都把整台汽车重新送到国家实验室做碰撞测试。

### 14.2 为什么会降低交付效率

问题发现得越晚，修复成本越高。如果 Main 开发者两天后才收到 Lab 反馈：

- 开发上下文已经丢失；
- 多个变更可能混在一起；
- 难以定位引入错误的 Workpack；
- 团队倾向于积累大批量变更；
- 大批量变更更难测试、更容易失败。

独立验证不应等于：

> 开发完成以后扔给另一个团队排队。

### 14.3 如何保持独立又避免排队

#### 自助调用固定工具

```text
Main 每次提交
→ 自动运行 Linkage CLI
→ 自动运行 Lab 快速 Fixture
→ 立即获得反馈
```

最终认证仍在独立环境中执行。

#### 分层测试

```text
每次提交：
快速 Contract、Hash 和静态检查

每个 Workpack：
相关 Fixture 和增量 Linkage

Release Candidate：
完整 Lab、篡改和端到端测试

真实安装前：
完整 Linkage D
```

#### 使用失效 DAG

只重跑被变更影响的：

```text
时间线 Workpack
→ 对应 Linkage
→ 对应 Lab Fixture
```

无需重跑与字幕、字体或代理文件无关的全部测试。

#### 风险分级

| 变更类型 | 建议验证 |
|---|---|
| 文档、注释 | 静态检查 |
| 内部重构 | 单元测试、相关 Linkage |
| 接口变更 | Contract、Linkage A/C |
| Artifact 构建变化 | Linkage B1、可复现构建 |
| 安装逻辑变化 | Installability、Linkage D |
| 安全或权限变化 | 完整 Lab 与人工门禁 |
| 真实目标安装 | 独立人工授权 |

## 15. 六项风险的组合优化

```text
自定义格式
→ 开放标准

只有 Hash
→ 签名身份和透明日志

名义独立
→ 可验证控制域隔离

Validator 自测
→ Golden Corpus、Mutation、交叉实现和外部验证

Evidence 爆炸
→ 分层证据和单一权威状态

工具发布队列
→ 自动化前移、增量验证和风险分级
```

# 第三部分：Codex AI Coding 与三个不同 CLI

## 16. 三个 CLI 的角色

Codex AI Coding 场景可以启用：

```text
CLI 1：Main Coding CLI
CLI 2：External Lab CLI
CLI 3：Linkage Review CLI
```

### 16.1 Main Coding CLI

负责：

- 读取 Start Package；
- 编写目标代码；
- 修改 Main 仓库；
- 运行开发测试；
- 构建 Artifact；
- 输出构建结果和本地 Evidence。

允许写：

```text
main_build/repository/
main_build/evidence/
main_build/artifacts/
```

禁止：

- 修改 Lab 测试规则；
- 修改 Linkage 判断逻辑；
- 修改认证结果；
- 自己签发 Conformance Certificate。

### 16.2 External Lab CLI

负责：

- 读取固定 Hash 的 Artifact；
- 运行正向、负向和篡改测试；
- 校验安装实例；
- 输出 Lab Finding 和认证 Evidence；
- 在条件满足时签发 Lab 结果。

允许写：

```text
external_lab/evidence/
external_lab/findings/
external_lab/certification/
```

禁止写：

```text
main_build/repository/
main_build/artifacts/
linkage_review/
```

### 16.3 Linkage Review CLI

负责只读核对：

- Requirement 与 Workpack；
- Workpack 与源码；
- 源码与 Artifact；
- Artifact 与安装实例；
- 安装实例与 Lab 报告；
- Lab 报告与证书。

允许写：

```text
linkage_review/evidence/
linkage_review/findings/
```

Main、Lab、Artifact 和历史 Ledger 对它都应是只读。

## 17. 为什么三个 CLI 仍可能只有逻辑独立

假设三个 CLI 运行在：

```text
同一个 Codex Task
同一个 Agent
同一个 macOS 用户
同一个工作目录
同一个 GitHub Token
同一个 Python 环境
同一个管理员权限
文件系统全部可写
```

虽然命令名称不同：

```bash
main-cli
lab-cli
linkage-cli
```

它们仍共享同一个控制主体。

Main 出错后，同一个 Codex Agent 仍可能：

1. 修改 Main；
2. 修改 Lab Validator；
3. 修改 Linkage 规则；
4. 重写 Evidence；
5. 重新计算 Hash；
6. 最后输出 PASS。

通俗类比：

> 同一个人打开三个终端窗口，分别写着“施工队”“质检员”“审计员”，不代表真的存在三方监督。

## 18. AI Coding 中应追求“控制域独立”

对于单用户 Codex，不一定存在三个真实公司或部门。

更实用的目标是：

> 让三个 CLI 属于三个可验证、相互不能越权的控制域。

控制域至少包括：

- 独立工作目录；
- 独立写权限；
- 独立运行进程；
- 独立凭证；
- 独立签名身份；
- 独立上下文；
- 独立日志；
- 独立判定代码。

## 19. 三个 CLI 的推荐隔离

### 19.1 工作目录和写权限隔离

```text
execution_root/
├── main_build/
│   └── repository/
├── external_lab/
│   └── repository/
└── linkage_review/
    └── repository/
```

| CLI | Main | Lab | Linkage | Artifact |
|---|---:|---:|---:|---:|
| Main CLI | 读写 | 不可写 | 不可写 | 只能发布新 Artifact |
| Lab CLI | 只读 | 读写 | 不可写 | 只读 |
| Linkage CLI | 只读 | 只读 | 只写自己的 Evidence | 只读 |

仅靠 Prompt 说“不要修改”不够，应由文件权限、容器挂载或沙箱强制。

### 19.2 Codex Task 和上下文隔离

推荐：

```text
Main Codex Task
→ 只接收需求和 Main Workpack

Lab Codex Task
→ 只接收锁定 Protocol、Artifact 和 Lab Workpack

Linkage Codex Task
→ 只接收锁定证据、Hash 和 Linkage Workpack
```

避免：

- Lab 被 Main 的实现思路影响；
- Linkage 因知道“预期应 PASS”产生确认偏差；
- 三个角色共享同一个错误假设；
- Main 中的提示注入影响 Lab。

不同 Task 只是上下文隔离，不等于权限隔离，二者必须同时存在。

### 19.3 运行环境隔离

理想状态：

```text
Main CLI
→ Main Container

Lab CLI
→ Clean Lab Container

Linkage CLI
→ Read-only Verification Container
```

Lab 不应复用 Main 的：

- 虚拟环境；
- 构建缓存；
- 可变依赖目录；
- 环境变量；
- Git 凭证；
- 运行账户。

### 19.4 身份和签名隔离

三个 CLI 使用不同执行身份：

```text
MAIN-CODEX-EXECUTOR
EXTERNAL-LAB-VALIDATOR
LINKAGE-READONLY-VERIFIER
```

分别签署：

```text
Main：
Artifact Provenance

Lab：
Validation Result

Linkage：
Linkage Report
```

Main 不应拥有 Lab 的签名能力。

### 19.5 不可变输入交接

Main 不应把一个可变目录直接交给 Lab。

正确交接：

```text
Main 可变仓库
→ 构建固定 Artifact
→ 计算 Hash
→ 签署 Provenance
→ 写入不可变 Artifact Store
→ Lab 按 Hash 读取
```

Lab 接收：

```text
artifact_sha256 = ABC123
```

而不是：

```text
请测试 /main/latest/
```

因为 `latest` 随时可能变化。

## 20. 三个 CLI 的实际协作

### 20.1 Main Coding CLI 构建

```text
Runtime 向 Main CLI 下发 MB-P2
→ Main CLI 校验 Workpack 和授权
→ 编写代码
→ 运行 Main 自测
→ 输出 Workpack Result
→ 构建 Artifact
→ 计算 Hash
→ 签署 Provenance
→ Main CLI 结束
```

Main 只能声明：

```text
BUILD_COMPLETED
MAIN_SELFTEST_PASS
ARTIFACT_READY
```

不能声明：

```text
CONFORMANCE_CERTIFIED
```

### 20.2 Linkage CLI 核对身份链

```text
Runtime 启动 Linkage CLI
→ 只读 Start Package
→ 读取 Main Workpack Result
→ 读取 Artifact 和 Provenance
→ 核对 Program ID、Source Hash、Command Hash、Artifact Hash
→ 输出 Linkage Report
→ 签署报告
→ Linkage CLI 结束
```

发现不一致：

```text
LINKAGE FAIL
→ Finding
→ 返回 Main Owner
```

Linkage 不能修改 Artifact 或报告中的 Hash。

### 20.3 Lab CLI 独立验证

```text
Runtime 创建干净 Lab 环境
→ Lab CLI 按固定 Hash 安装 Artifact
→ 核对安装来源
→ 运行正向、负向和篡改测试
→ 生成 Lab Evidence
→ 签署 Lab Result
```

失败时：

```text
Lab Finding
→ 指定 Main Owner
→ 返回相应 Workpack
→ Main 重新构建新 Artifact
```

Lab 不能进入 Main 仓库直接修复。

## 21. 三 CLI 的共同故障风险

即使权限分开，如果三个 CLI：

- 来自同一个代码库；
- 复用同一个 Validator 核心；
- 使用同一套依赖；
- 使用同一个模型和同一套提示；
- 根据同一个错误 Schema 实现；

它们仍可能同时犯同一个错误。

例如：

```text
Main CLI 认为时间容差是 10 秒
Lab CLI 导入同一个容差函数
Linkage CLI 读取同一个错误 Schema
```

三者全部 PASS，但规范实际只允许 100 毫秒。

因此：

- 可以共享规范 Schema；
- 可以共享 Program ID 等基础结构；
- 不应共享最终 PASS/FAIL 判定实现；
- Lab Validator 应独立实现；
- Linkage 应只验证证据关系；
- 高风险规则应使用第二套实现交叉验证。

## 22. Codex 场景的独立性等级

### L0：三个 CLI 名称

```text
同一 Task
同一权限
同一目录
三个命令入口
```

只有形式上的角色分离。

### L1：三个独立进程

```text
不同 CLI 进程
共享文件系统和凭证
```

具备进程隔离，但仍可互相修改。

### L2：三个独立 Workspace

```text
独立目录
独立 Codex Task
独立日志
受限写路径
```

已经具备可用的工程隔离。

### L3：三个独立控制域

```text
独立容器或账户
独立凭证
独立签名身份
不可变 Artifact 交接
Append-only Evidence
```

适合作为高可信 AI Coding 目标。

### L4：外部独立验证

```text
独立组织或人工 Reviewer
独立基础设施
独立管理责任
```

适合正式监管或安全关键认证。

建议：

> 默认达到 L2，正式候选和高风险发布达到 L3，真实安装或正式证书保留 L4 人工或外部确认。

## 23. Runtime 对三个 CLI 的约束

Runtime 不能只是依次执行三个命令，而要建立独立执行合同：

```json
{
  "executor_identity": "EXTERNAL-LAB-VALIDATOR",
  "allowed_read_roots": [
    "/immutable/start-package",
    "/immutable/artifacts/ABC123"
  ],
  "allowed_write_roots": [
    "/execution/evidence/external-lab"
  ],
  "forbidden_write_roots": [
    "/execution/main-build",
    "/execution/linkage-review"
  ],
  "command_manifest_sha256": "...",
  "max_transitions": 5,
  "expires_at": "..."
}
```

执行前后验证：

- 实际 CLI 路径；
- CLI 文件 Hash；
- 当前身份；
- 读取和写入路径；
- 环境身份；
- 输入 Artifact Hash；
- 输出 Evidence Hash；
- 是否出现越权写入；
- 是否使用其他 CLI 的签名身份。

## 24. 推荐的 Codex 三 CLI 架构

```text
                    Controlled Runtime
                           │
           ┌───────────────┼───────────────┐
           │               │               │
     Main Coding CLI    Linkage CLI      Lab CLI
           │               │               │
      可写 Main         Main/Lab 只读     Main 只读
      不可写 Lab        可写 Finding      可写 Lab Evidence
      不可写 Linkage    不可改历史         可签 Lab Result
           │               │               │
           └───────不可变 Artifact/Evidence Bus───────┘
```

三个 CLI 不直接互相调用，而是由 Runtime 调度，通过不可变 Artifact 和 Evidence 交换结果。

避免：

```text
Main CLI 直接调用 Lab CLI
并传入一个可变目录
```

推荐：

```text
Runtime 接收 Main Result
→ 验证并锁定 Artifact
→ Runtime 启动 Linkage CLI
→ 验证 Linkage Result
→ Runtime 启动 Lab CLI
```

## 25. 最终结论

三个不同 CLI 是实现独立性的良好基础，但不是充分条件。

如果只是：

```text
同一个 Codex Agent
+ 三个命令名称
+ 同一套 unrestricted 权限
```

那么仍然只是逻辑独立。

如果进一步实现：

```text
独立 Codex Task
+ 独立 Workspace
+ 独立写权限
+ 独立运行环境
+ 独立签名身份
+ 不可变 Artifact 交接
+ Append-only Evidence
+ 不共享最终判定代码
```

三个 CLI 才形成真正可验证的技术独立。

最通俗的判断标准是：

> Main CLI 做错事以后，是否有能力同时修改 Lab 规则、Linkage 报告和历史 Evidence？

如果答案是“有”，还没有真正独立。

如果系统权限让它做不到，独立性才是有效的。

最终理想状态是：

```text
外部工具看得懂 Evidence
关键证据具有签名身份
独立性能够分级和证明
Validator 会被交叉校准
用户能够快速看到结论
开发者能够立即获得反馈
高风险操作仍由独立角色和人工门禁控制
```
