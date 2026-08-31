# Start Package 三工程架构详解、文献对照与优化评估

> 适用对象：`Codex_Video_Editor_Plugin_Hybrid_Start_Package_v0_3`  
> 文档性质：架构解释与评估，不构成运行、认证或安装结果  
> 当前事实边界：v0.3 中的 Main、External Lab、Linkage Review 均为 `PLANNED_NOT_STARTED`

## 1. 一句话理解

Start Package 内部规划的不是一个工程，而是三个相互制衡的工程：

1. **主执行工程（Main Build）**：负责真正开发、构建和打包目标产品。
2. **独立校验工程（External Conformance Lab）**：负责制定独立检测规则、构建检测工具并作出认证判断。
3. **联通核验工程（Read-only Linkage Review）**：负责证明需求、源码、Artifact、安装实例、测试结果和证书始终属于同一条可信链。

通俗地说：

- Main 是施工队；
- External Lab 是第三方质检实验室；
- Linkage Review 是防伪验货员；
- Runtime/Driver 是总调度员；
- Start Package 是三方共同遵守、不可在执行中随意修改的施工与验收合同。

```text
先造考试规则和检测仪器
→ 再造身份核验和防伪工具
→ 然后建设主产品
→ 核对送检件与构建件是否一致
→ 在独立环境中正式检测
→ 形成证书与发布锁
```

## 2. Start Package 中实际包含什么

v0.3 在 `project_start_packages/` 下规划了三个项目启动包：

```text
project_start_packages/
├── main_build/
├── external_lab/
└── linkage_review/
```

每个项目启动包都包含：

- `PROJECT_CHARTER.md`：项目使命、权限和禁止事项；
- `PROJECT_STATE.json`：初始状态；
- `WORKPACK_INDEX.json`：Workpack、依赖、产出和执行顺序；
- `COMMAND_MANIFEST.json`：允许调用的命令入口；
- `BUILD_INSTALL_PLAN.md`：项目物化、隔离环境和安装计划；
- README：使用入口和 Authoring Stop 声明。

它们目前只是项目合同，不是已经建好的三个仓库。真正运行时，Controlled Runtime 读取 Start Package，在独立 execution root 中物化项目仓库、Driver、SQLite、Ledger 和 Evidence 目录。

## 3. 主执行工程：负责把产品做出来

### 3.1 身份与职责

```text
project_id   = MAIN_HARNESS_BUILD
project_role = MAIN_BUILD_PROJECT
```

Main Build 负责：

- 创建目标代码仓库；
- 实现 Codex Video Editor Plugin 与 Harness；
- 实现需求、接口、验证器和运行能力；
- 完成 G0、P1、P2、P3、P4；
- 构建不可变 Artifact；
- 生成发布候选；
- 产生本地验证、构建和安装准备证据。

### 3.2 Workpack 结构

| Workpack | 作用 | 典型输出 |
|---|---|---|
| `MB-G0` | 锁定章程、控制面和执行边界 | `G0_CONTROL_LOCK_VALID` |
| `MB-P1` | 建立基础工程和核心骨架 | `P1_BUILD_LOCK_VALID` |
| `MB-P2` | 完成主要能力 | `P2_BUILD_LOCK_VALID` |
| `MB-P3` | 完成集成阶段，或经过人工批准声明 N/A | `P3_BUILD_LOCK_VALID` |
| `MB-P4` | 完成本地闭环、打包和可安装性准备 | `P4_LOCAL_GATE_PASS` |
| `MB-RELEASE-CANDIDATE` | 形成发布候选 | `MAIN_RELEASE_CANDIDATE_PREPARED` |

推进关系不是“运行完脚本就算成功”，而是能力依赖：

```text
G0_CONTROL_LOCK_VALID
→ P1_BUILD_LOCK_VALID
→ P2_BUILD_LOCK_VALID
→ P3_BUILD_LOCK_VALID
→ P4_LOCAL_GATE_PASS
→ MAIN_RELEASE_CANDIDATE_PREPARED
```

每一步都必须同时满足：

- 前置能力存在；
- Workpack 与 Command Manifest Hash 未漂移；
- 授权覆盖当前 DAG Node、命令和写入根；
- postflight 和 independent review 通过；
- Evidence 已进入可信事件链。

### 3.3 为什么 Main 不能自我认证

Main 可以证明“我完成了构建，并产生了这些证据”，但不能独立证明“我的产品符合全部外部要求”。否则会形成自己设计、自己出题、自己改卷、自己发证的闭环。

因此 Main：

- 可以做单元、集成和本地验收；
- 不能签发 Conformance Certificate；
- 不能修改 External Lab 的判定规则；
- 不能因为构建成功就触发真实目标安装；
- 必须把失败修复和重新验证记录在失效 DAG 中。

## 4. 独立校验工程：负责造考卷和检测仪器

### 4.1 身份与职责

```text
project_id   = EXTERNAL_CONFORMANCE_LAB
project_role = EXTERNAL_CONFORMANCE_LAB
```

External Lab 负责：

- 定义 Conformance Protocol 和证据 Schema；
- 开发独立验证 CLI；
- 建立正向、负向和篡改 Fixture；
- 校验 Trusted Runner Attestation；
- 在干净认证环境中安装固定 Hash 的候选 Artifact；
- 根据完整证据作出 PASS、FAIL 或证书判断。

### 4.2 Workpack 结构

| Workpack | 通俗含义 | 主要产出 |
|---|---|---|
| `LAB-PROTOCOL` | 制定考试规则和答卷格式 | `LAB_PROTOCOL_SCHEMA_PASS` |
| `LAB-CLI` | 开发检测仪器 | `LAB_CLI_READY` |
| `LAB-FIXTURES` | 准备正确、错误和恶意样本 | `POSITIVE_AND_NEGATIVE_FIXTURES_READY` |
| `LAB-SELFTEST` | 先验证检测仪器自身 | `LAB_SELFTEST_PASS` |
| `LAB-CERTIFICATION` | 对最终安装实例正式检测 | `LAB_INSTALLED_TEST_EVIDENCE_READY` |

### 4.3 为什么 Lab 在 Main 之前建设

如果产品做完以后才定义验收标准，测试容易迁就现有实现。先锁定 Protocol、Fixture 和判定规则，可以降低以下风险：

- 只覆盖成功路径；
- 为已有实现定制“容易通过”的规则；
- 把主工程自报结果当作独立证据；
- 在失败后悄悄修改判定标准；
- 测试的对象并非最终发布对象。

这与 NASA 的 Independent Verification and Validation 思想一致：验证活动需要在技术和管理上独立，并由验证方独立选择分析对象、技术和问题。NASA 还区分了 Verification——“是否正确地构建产品”，与 Validation——“是否构建了正确的产品”。参见 [NASA IV&V Overview](https://www.nasa.gov/ivv-overview/)。

ISO/IEC 17025 则强调实验室的能力、公正性和持续一致的运行。该思想支持 External Lab 不受 Main 交付压力影响，并要求检测工具、人员、环境和报告本身也具有可信度。参见 [ISO/IEC 17025:2017](https://www.iso.org/standard/66912.html)。

### 4.4 Lab 的边界

External Lab 不得：

- 修改 Main 源码；
- 替 Main 修复失败；
- 使用 Main 自测代替独立检测；
- 在证据不完整时发证；
- 把 Lab 工具环境安装等同于真实业务目标安装。

失败时应输出结构化 Finding：

```text
Finding:
候选 Artifact 的接口输出不符合 Protocol

Owner:
MAIN_HARNESS_BUILD

Return Path:
回到对应 Main Workpack 修复
→ 重新构建 Artifact
→ 重新执行 Linkage
→ 重新进入 Lab
```

## 5. 联通核验工程：负责证明“从头到尾都是同一个东西”

### 5.1 身份与职责

```text
project_id   = CONFORMANCE_LINKAGE_REVIEW
project_role = READ_ONLY_LINKAGE_REVIEW
```

Linkage Review 不只是检查 API 能否调用。它检查的是跨工程、跨版本和跨阶段的身份与证据连续性：

```text
Requirement Atom
→ Workpack
→ 源码
→ 构建 Artifact
→ Artifact Hash
→ 安装 Receipt
→ Installed Target Descriptor
→ Lab 测试
→ Certificate
```

任何一段出现 Program ID、版本、Hash、来源、授权或环境不一致，都必须停止。

### 5.2 为什么需要独立 Linkage

假设：

- A 版本通过了测试；
- B 版本被安装；
- C 版本的 Hash 被写进证书。

每一个局部步骤都可能显示 PASS，但整条链实际上是假的。Linkage Review 专门发现这种“局部正确、整体接错”的问题。

这与 in-toto 的核心思想高度相似：软件供应链由多个独立参与者和步骤组成，需要记录每一步使用的命令、输入、输出与授权主体，形成可验证的连续链。参见 [in-toto USENIX Security 2019 论文](https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias)及其[项目说明](https://github.com/in-toto/in-toto)。

SLSA 也将 Producer、Verifier 和 Consumer 分为不同角色，并要求消费者或独立 Verifier 根据 Provenance 判断 Artifact 是否来自预期来源和可信构建平台。参见 [SLSA v1.1 Terminology and Verification Model](https://slsa.dev/spec/v1.1/terminology)。

### 5.3 Workpack 结构

| Workpack | 通俗含义 | 主要产出 |
|---|---|---|
| `LINK-PROTOCOL` | 定义跨工程证据怎样互相引用 | `LINK_PROTOCOL_SCHEMA_PASS` |
| `LINK-CLI` | 开发只读核验工具 | `LINK_CLI_READY` |
| `LINK-SELFTEST` | 验证 Linkage 工具不误判、不越权写入 | `LINK_SELFTEST_PASS` |
| `LINK-PREFLIGHT` | 主构建或发布前检查接口和证据是否接通 | `LINKAGE_A_EVIDENCE_READY` |
| `LINK-D` | 安装后核对构建件、安装件和认证对象 | `LINKAGE_D_EVIDENCE_READY` |

### 5.4 Linkage A、B0、C、B1、D

#### Linkage A：接口完整性

确认 Main 和 Lab 使用同一 Protocol、Schema 和证据接口。

通俗理解：

> 确认插头和插座型号一致。

#### Linkage B0：规范绑定

确认候选包绑定正确的 Charter、Profile、Requirement Atom 和 Program ID。

通俗理解：

> 确认产品是按正确图纸制造的。

#### Linkage C：证据兼容性

确认 Main 产生的 Receipt 和 Evidence 能被独立 Lab 读取，而不是只有 Main 自己能够解释。

通俗理解：

> 确认施工队的检测报告可以被第三方实验室复核。

#### Linkage B1：Artifact 绑定

确认发布候选 Artifact 来自已审核源码，送检后没有被替换或重新打包。

通俗理解：

> 给送检产品贴上防伪封条。

#### Linkage D：安装后握手

确认认证环境实际安装的对象与已锁定 Artifact 完全一致。

通俗理解：

> 开箱后再次核对序列号，确认没有换货。

### 5.5 Linkage 的只读原则

Linkage 只能输出：

- PASS；
- FAIL；
- Finding；
- Repair Route。

它不得：

- 修改 Main；
- 修改 Lab；
- 修改 Artifact；
- 修改安装环境；
- 修改历史 Evidence；
- 签发 Conformance Certificate。

## 6. 三工程的完整工作顺序

```text
Start Package Human Approval
→ Shared Control Baseline Lock
→ Control Plane Registration
→ Driver Runtime Verification

→ External Lab Bootstrap
→ LAB-PROTOCOL
→ LAB-CLI
→ LAB-FIXTURES
→ LAB-SELFTEST
→ Lab Tool Release Lock

→ Linkage Review Bootstrap
→ LINK-PROTOCOL
→ LINK-CLI
→ LINK-SELFTEST
→ Linkage Tool Release Lock

→ Main Execution Package Materialization
→ Main Package Validation
→ Main Program Registration
→ MB-G0
→ MB-P1
→ MB-P2
→ MB-P3
→ MB-P4

→ Release Pipeline
→ Linkage A/B0/C
→ Immutable Artifact Build
→ Linkage B1
→ Installability Verification
→ Release Candidate Lock
→ Certification Environment
→ Install Once
→ Linkage D
→ Lab Positive/Negative/Tamper Tests
→ C4 Report
→ Conformance Certificate
→ Certified Release Lock
→ Wait Real Target Install Authorization
```

注意：Lab 和 Linkage 在 Main 之前建设的是检测工具，不是提前认证一个尚不存在的产品。正式认证必须等待固定 Hash 的候选 Artifact 和干净认证环境。

## 7. 三种“验证”不能混为一谈

| 验证类型 | 回答的问题 | 是否能发证 |
|---|---|---|
| Main 自测 | 产品在开发环境中能否工作 | 否 |
| Linkage 核验 | 需求、源码、Artifact、安装件和证据是不是同一条链 | 否 |
| External Lab 认证 | 固定 Hash 的安装实例是否符合规范 | 是 |

最简单的记忆方式：

```text
Main：东西能不能工作
Linkage：检查的是不是同一个东西
External Lab：这个东西到底达不达标
```

## 8. Runtime 和 Driver 的位置

Runtime 不属于三个工程，它是通用执行控制面。Driver 也不是第四个工程，而是项目专属调度器。

Driver 根据 `ENGINEERING_PROJECT_DAG.json` 执行：

1. 读取当前状态；
2. 选择唯一合法后继；
3. 校验授权、命令 Hash、写入根和预算；
4. 执行 Workpack；
5. 执行 readback、postflight 和 independent review；
6. 写入 Evidence Hash 和事件链；
7. promotion、进入 Finding/Fix，或 hard stop。

因此 Driver 不是按文件名机械运行脚本，而是根据“前置能力 → 当前任务 → 验收能力”的状态机推进。

## 9. 正式文献对照

### 9.1 NASA IV&V：支持独立验证

NASA 将独立性拆为技术、管理和财务维度，并强调 IV&V 应独立选择分析对象、方法与问题。三工程中的 External Lab 与 Main 分离，方向上符合这一原则。

但当前 Start Package 主要证明“逻辑角色分离”，尚未证明人员、组织、预算和基础设施也真正独立。因此不能把架构角色直接等同于完整 NASA 级 IV&V。

来源：[NASA IV&V Overview](https://www.nasa.gov/ivv-overview/)、[NASA Software IV&V Guidance](https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695499/SWE-141%2B-%2BSoftware%2BIndependent%2BVerification%2Band%2BValidation)。

### 9.2 ISO/IEC 17025：支持 Lab 的公正性和能力证明

ISO/IEC 17025 强调实验室的能力、公正性和持续一致运行。External Lab 的独立工具、自测、干净环境和证书边界与其方向一致。

当前缺口是：Lab 尚无外部能力认可、校准制度、人员能力模型和正式测量不确定度。因此更准确的说法是“借鉴实验室治理思想”，而不是“已经满足 ISO/IEC 17025”。

来源：[ISO/IEC 17025:2017](https://www.iso.org/standard/66912.html)。

### 9.3 in-toto 与 SLSA：支持供应链证据链

in-toto 通过布局、授权参与者和每一步的 link metadata，验证供应链是否按计划执行。SLSA 则使用 Provenance 描述 Artifact 在何时、何地、通过什么输入和平台产生。

Linkage Review 中的 Program ID、Artifact Hash、Command Manifest Hash、安装描述和 Evidence 链与上述思想高度一致。

但当前系统主要依赖 SHA256 和本地事件链，尚未全面使用标准 in-toto Attestation、DSSE Envelope、SLSA Provenance 或透明日志。因此它是“同类思想的自定义实现”，互操作性仍有限。

来源：[in-toto USENIX 论文](https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias)、[SLSA v1.2 Specification](https://slsa.dev/spec/v1.2/)、[SLSA Provenance](https://slsa.dev/spec/v1.2/provenance)。

### 9.4 NIST SSDF：支持把安全验证嵌入整个生命周期

NIST SSDF 主张把安全软件开发实践集成进现有 SDLC，而不是只在发布前增加一次安全检查。当前架构将需求、构建、Artifact、安装和认证都纳入验证，方向正确。

来源：[NIST SP 800-218 SSDF v1.1](https://csrc.nist.gov/pubs/sp/800/218/final)。

### 9.5 DORA：支持自动化，但警告重型审批

DORA 研究认为，重型外部审批会降低交付性能，而且没有证据表明它一定能降低变更失败率。更好的方式是把同行评审、自动测试、安全控制和快速反馈前移，只把真正的风险决策保留给人工。

这支持当前架构中的：

- A3 bounded automation；
- 自动推进到真实 Human Gate；
- 使用证据和 policy 代替逐节点人工确认；
- 将真实安装、范围扩展和 waiver 保留为人工决策。

它也提醒本架构：如果 Lab、Linkage 和 Main 变成三个排队交接的组织，系统会重新产生大量等待。

来源：[DORA Streamlining Change Approval](https://dora.dev/capabilities/streamlining-change-approval/)、[DORA Continuous Delivery](https://dora.dev/capabilities/continuous-delivery/)。

### 9.6 Contract Testing：支持接口前移，但不能代替端到端测试

契约测试可以更快验证组件边界，但不能证明完整业务流一定正确。Linkage A 和 Protocol 自测适合采用契约测试；最终安装实例仍需 External Lab 的端到端、负向和篡改测试。

来源：[Martin Fowler — Testing Strategies in a Microservice Architecture](https://martinfowler.com/articles/microservice-testing/fallback.html)、[Pact Specification](https://docs.pact.io/implementation_guides/pact_specification)。

## 10. 工程论坛观点

论坛观点属于经验材料，不等同于标准或科学结论，但能揭示实际落地摩擦。

### 10.1 支持独立 QA 的观点

Software Engineering Stack Exchange 的讨论认为，开发团队仍应负责基础测试；在受监管或高风险场景，独立 QA/IV&V 具有额外价值。该观点支持“Main 负责质量，External Lab 负责独立保证”，而不是把全部质量责任甩给 Lab。

来源：[Is separate QA team redundant?](https://softwareengineering.stackexchange.com/questions/344373/is-separate-qa-team-redundant-in-development-life-cycle)。

### 10.2 反对“扔过墙式 QA”的观点

Reddit DevOps 社区的实践讨论反复提到：如果开发、测试和发布完全分成排队队列，测试团队会成为瓶颈，责任归属也会变得模糊。常见建议是把可自动化测试放入 CI，为变更建立临时隔离环境，并让测试能力前移。

来源：[How do you work with testing teams?](https://www.reddit.com/r/devops/comments/13mxhqh)。

对本架构的启示是：

> 角色和证据必须独立，但反馈回路不能割裂。

External Lab 可以保持判定权独立，同时把 Protocol、Fixture 和 CLI 作为 Main 日常开发可调用的只读工具，尽早暴露失败。

### 10.3 供应链工具复杂度观点

Hacker News 关于供应链 Attestation 的讨论一方面认可离线可验证证据、in-toto 和跨组织互操作；另一方面也反映出开发者对 SLSA 层级、Attestation 工具和额外操作复杂度的困惑。

来源：[Software supply-chain review tooling discussion](https://news.ycombinator.com/item?id=32904192)、[Chainloop: a supply-chain attestation solution developers will use](https://news.ycombinator.com/item?id=35180648)。

这意味着本架构不能只做到“理论严谨”，还必须提供：

- 一条命令完成常规验证；
- 明确的 `why blocked`；
- 唯一 Return Path；
- 自动生成 Evidence；
- 默认隐藏不影响当前决策的复杂字段；
- 对低风险变更进行门禁裁剪。

## 11. 这套体系是否先进

### 11.1 结论

这套体系在**架构思想上先进**，尤其适合高风险、强审计、Agent 自动执行和软件供应链完整性场景；但它目前仍属于**高级工程设计与实现验证阶段**，不能仅凭 Start Package 声明它已经达到成熟工业认证体系。

### 11.2 分项评价

| 维度 | 评价 | 原因 |
|---|---|---|
| 职责分离 | 先进 | Main、Verifier、Certificate Authority、Driver 权限分离 |
| 证据链 | 先进 | Requirement、Workpack、Artifact、安装和证书均有 Hash 绑定 |
| 自动化控制 | 先进 | A3 有预算、作用域、停止条件和恢复路径 |
| 失败治理 | 较先进 | Finding、bounded fix、失效 DAG、hard stop 分离 |
| 独立验证 | 方向先进 | 接近 NASA IV&V 和 ISO 实验室治理思想 |
| 开放标准兼容 | 有明显缺口 | 主要是自定义 JSON、Hash 和 Event Store |
| 密码学保证 | 有明显缺口 | Hash 能发现变化，但不能单独证明由谁产生和授权 |
| 流程效率 | 存在风险 | 三工程可能演变成三个排队队列 |
| 实证成熟度 | 尚待证明 | v0.3 三工程仍是 `PLANNED_NOT_STARTED` |
| 可理解性 | 偏复杂 | DAG、Workpack、Capability、Gate、Evidence 概念较多 |

### 11.3 最突出的先进点

1. **把“产品能运行”和“产品可信”分开。**
2. **把 Artifact 身份贯穿到安装和认证。**
3. **不让 Bootstrap 自动获得执行授权。**
4. **不让 Lab 修改 Main，也不让 Linkage 修正历史。**
5. **允许机器在 A3 预算内连续推进，但保留真正人工门禁。**
6. **把 Acceptance Failure 与普通临时 Retry 分开。**

### 11.4 最大风险

1. **流程过重**：低风险项目也走完整三工程，会造成成本失配。
2. **格式自定义**：外部工具难以直接消费 Evidence。
3. **只有 Hash、缺少签名**：能检测内容变化，但身份和授权证明仍偏弱。
4. **逻辑独立不等于组织独立**：同一人、同一机器、同一权限运行三工程时，独立性可能只是名义上的。
5. **验证器自测悖论**：Lab 自测通过不代表 Lab 判断永远正确，需要交叉实现、Golden Corpus 或外部验证。
6. **Evidence 爆炸**：每个节点都记录大量 Hash、Receipt 和 Readback，可能降低可用性。
7. **工具发布队列**：如果 Main 每次变更都等待 Lab/Linkage 人工处理，会违背 DORA 的快速反馈原则。

## 12. 优化方向

### 12.1 P0：在真实执行前必须完成

#### 1. 引入签名 Attestation，而不只依赖 SHA256

建议把关键事件输出为标准 in-toto/DSSE Attestation，并对以下对象签名：

- Requirement Freeze；
- Workpack Result；
- Artifact Provenance；
- Installed Target Descriptor；
- Lab Result；
- Conformance Certificate。

Sigstore 的 keyless signing 可将短期密钥与 OIDC 身份绑定，并把签名事件写入透明日志，增强“由谁产生”和“是否被隐藏替换”的证明。参见 [Sigstore Signing Overview](https://docs.sigstore.dev/cosign/signing/overview/)。

#### 2. 建立可复现构建

固定：

- 源码；
- 依赖；
- 构建命令；
- 工具链版本；
- 环境描述；
- 输出 Artifact。

使独立参与方能够从相同输入重建 bit-for-bit 一致结果。参见 [Reproducible Builds Definition](https://reproducible-builds.org/docs/definition/)。

#### 3. 明确真正的独立性等级

建议增加：

```text
INDEPENDENCE_L0 = 仅逻辑角色不同
INDEPENDENCE_L1 = 不同进程和写权限
INDEPENDENCE_L2 = 不同账户和隔离环境
INDEPENDENCE_L3 = 不同管理域或外部机构
```

证书必须声明实际达到的独立性等级，避免把“同一机器上的三个目录”描述为第三方认证。

#### 4. 为 Driver 增加 explain surface

每次停止应直接输出：

```text
为什么停
缺少什么
谁负责
哪些 Hash 受影响
唯一合法下一步
是否需要人工
```

避免用户直接阅读完整 DAG 和 Ledger。

### 12.2 P1：降低流程成本

#### 1. 风险分级，而不是所有项目固定三套强门禁

建议定义：

| 风险等级 | 推荐路径 |
|---|---|
| 低风险 | Main 自测 + 自动 Linkage + 抽样 Lab |
| 中风险 | Main + 完整 Linkage + 自动 Lab |
| 高风险 | 三工程完整独立 + 人工关键门禁 |
| 受监管/安全关键 | 外部 IV&V + 强签名 + 可复现构建 + 多方审批 |

#### 2. 保持角色独立，但消除排队交接

- Lab Protocol 和 Fixture 在 Main 开发阶段即可调用；
- Linkage CLI 在每次 PR/Workpack 后自动执行；
- 人工只处理无法自动判定的风险；
- Finding 自动路由给 Owner；
- 修复后只重跑失效 DAG 覆盖范围，不全量重跑。

#### 3. 合并重复校验

建立统一 Evidence Schema，避免 Main、Linkage、Lab 对同一 Hash、Program ID 和路径重复实现三套解析逻辑。

### 12.3 P2：提升开放性和可审计性

#### 1. 对齐开放标准

- Provenance：SLSA/in-toto；
- 签名：Sigstore/DSSE；
- SBOM：SPDX，参见 [SPDX Specifications](https://spdx.dev/use/specifications/)；
- Findings：SARIF 或可映射的通用 Finding Schema；
- Policy：可执行 Policy-as-Code；
- Trace：OpenTelemetry 兼容标识。

#### 2. 建立“验证验证器”的机制

- Golden Corpus；
- Mutation Testing；
- Differential Testing；
- 两套独立实现交叉验证；
- 外部 Challenge Fixture；
- 定期校准和盲测。

#### 3. 使用量化指标优化流程

建议持续测量：

- 从 Workpack 完成到独立结果的等待时间；
- 自动通过比例；
- 人工 Gate 数量；
- Finding 重现率；
- 无效 Finding 比例；
- Evidence 重建时间；
- Hash drift 发生率；
- Change Lead Time；
- Change Failure Rate；
- 自动修复成功率；
- hard stop 平均恢复时间。

## 13. 推荐的目标形态

理想状态不是删除 External Lab 或 Linkage Review，而是：

```text
Main 对质量负责
Lab 对独立判定负责
Linkage 对证据连续性负责
Runtime 对执行一致性负责
Human 对风险决策负责
```

同时做到：

```text
角色独立
≠ 团队割裂

证据完整
≠ 用户必须阅读全部证据

人工负责关键风险
≠ 每个节点都要人工点击

严格控制
≠ 所有项目使用同一重量级流程
```

## 14. 最终评价

这套体系的核心思想是先进的：它把独立验证、软件供应链 Provenance、内容寻址、权限隔离、有限自动化和恢复治理组合在同一套 Program DAG 中。

其真正价值不在于文件多或门禁多，而在于回答四个传统流水线经常回答不清的问题：

1. 现在运行的究竟是哪一份需求和代码？
2. 被测试、被安装和被认证的是不是同一个 Artifact？
3. 这个 PASS 是谁、在什么环境、依据什么证据作出的？
4. 失败以后应由谁修复，并从哪个可信节点重新进入？

但要从“先进架构”升级为“先进且高效的生产体系”，下一阶段必须重点解决：

- 开放标准兼容；
- 签名和身份可信；
- 可复现构建；
- 真正的独立性证明；
- 风险分级；
- 自动化前移；
- Evidence 可读性；
- 门禁和等待时间量化。

因此最准确的判断是：

> 架构方向先进，安全与审计思路完整；当前仍需通过真实三工程运行、独立环境、标准 Attestation 和交付效率数据，证明它不仅“严谨”，而且“可持续、高效、可互操作”。

## 15. 参考资料

### 标准、研究与正式资料

1. [NASA IV&V Overview](https://www.nasa.gov/ivv-overview/)
2. [NASA Software Independent Verification and Validation](https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695499/SWE-141%2B-%2BSoftware%2BIndependent%2BVerification%2Band%2BValidation)
3. [ISO/IEC 17025:2017](https://www.iso.org/standard/66912.html)
4. [NIST SP 800-218 Secure Software Development Framework](https://csrc.nist.gov/pubs/sp/800/218/final)
5. [in-toto: Providing farm-to-table guarantees for bits and bytes](https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias)
6. [in-toto GitHub Repository](https://github.com/in-toto/in-toto)
7. [SLSA v1.2 Specification](https://slsa.dev/spec/v1.2/)
8. [SLSA Provenance](https://slsa.dev/spec/v1.2/provenance)
9. [SLSA v1.1 Terminology and Verification Model](https://slsa.dev/spec/v1.1/terminology)
10. [DORA Streamlining Change Approval](https://dora.dev/capabilities/streamlining-change-approval/)
11. [DORA Continuous Delivery](https://dora.dev/capabilities/continuous-delivery/)
12. [Pact Specification](https://docs.pact.io/implementation_guides/pact_specification)
13. [Testing Strategies in a Microservice Architecture](https://martinfowler.com/articles/microservice-testing/fallback.html)
14. [Sigstore Signing Overview](https://docs.sigstore.dev/cosign/signing/overview/)
15. [Reproducible Builds Definition](https://reproducible-builds.org/docs/definition/)
16. [SPDX Specifications](https://spdx.dev/use/specifications/)

### 工程社区讨论

1. [Software Engineering Stack Exchange: Is separate QA team redundant?](https://softwareengineering.stackexchange.com/questions/344373/is-separate-qa-team-redundant-in-development-life-cycle)
2. [Reddit DevOps: How do you work with testing teams?](https://www.reddit.com/r/devops/comments/13mxhqh)
3. [Hacker News: Software supply-chain review tooling discussion](https://news.ycombinator.com/item?id=32904192)
4. [Hacker News: Chainloop and developer-friendly attestation](https://news.ycombinator.com/item?id=35180648)
