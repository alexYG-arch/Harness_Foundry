# Foundry GitHub 发布验收补充 v0.1

日期：2026-09-20。状态：`RESEARCHED_PLAN_SUPPLEMENT / NOT_IMPLEMENTED_NOT_RELEASE_APPROVAL`。

后续执行更新：用户已选择 MIT 和唯一正式仓库 `alexYG-arch/Harness_Foundry`。
具体工程进度以现有 Tracker 与[发布准备说明](RELEASE_READINESS.md)为准；下文保留检索时
快照，不把局部源码检查、许可选择或工作流文件存在当作已完成平台配置/发布验收。

本补充响应“检索 Git 上的正式发布标准”。以 GitHub 官方文档、SemVer、PyPA 和
OpenSSF 原始资料为依据，映射到既有 W6/W7，不建立另一套权威状态、认证或逐包审批。
没有执行安装、打包、目标任务、Git 推送、远端设置修改或发布；许可证和发布目的地不代用户选择。

## 1. 先区分三个层次

- **GitHub 平台机制：** Release 基于 Git tag，提供说明与附件分发；GitHub 自动提供的源码归档只是 tag 对应仓库内容，不证明完整可运行交付。
  见 [GitHub About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。
- **可选择采用的规范/实践：** SemVer 约束采用它的版本承诺；PyPA 规范适用于对应 Python 分发格式；OpenSSF 的 MUST 是其徽章条件，不是所有 GitHub 仓库必须满足的发布法律或平台门槛。
- **Foundry 自己的产品验收：** 搭建文档 Review、真实建设、独立验收、修复/恢复、同包双案例和独立接入仍按主计划执行。Release 页面、徽章和 CI 绿色都不能替代这些结果。

以下“建议必需”是针对已确认 Foundry 交付目标的工程补充，并非声称 GitHub 强制要求。
既有 G1–G13 不删除、不降级；新增建议在后续实施时使用原 Tracker 和缺陷账本，不新增状态系统。

## 2. 本地核对事实及边界

本次只读检查 Git 已跟踪文件和非运行目录中的文件清单：

- 未发现标准 `LICENSE`/`COPYING`/`NOTICE` 文件；`pyproject.toml` 未声明 license 或 license-files。
  这是发布前需要澄清的许可缺口，不代表已完成全部代码来源和授权审计。
- 未发现 `.github/` 工作流、`SECURITY.md`、`CONTRIBUTING.md`、`SUPPORT.md` 或标准 CHANGELOG 文件。
  已有 README 与日期更新说明；不能把“没有固定文件名”直接等同于所有内容均缺失。
- 产品元数据版本为 0.2.0，协议目标为 2.9；两者应保持清楚区分。
- 配置了 Harness_Foundry 与 harness-foundry-2.9 两个远端；本地 tag 清单为空。
  本次未查询远端 Release/Actions/Ruleset 状态，不能据此断言远端无发布、无 CI 或未设保护。
- 私有运行输入、控制库和命令附件不随公开仓库分发。公开复现不能依赖这些私有材料。

## 3. 建议补入的发布要求

### 3.1 使用许可、归属与支持入口 — W6 / W7C

**建议必需：** 用户明确选择对外使用许可；核对有实际分发的上游代码/资源许可并保留必要声明。
若宣称开源，提供相应开源许可文件，包内也应包含。不能把“仓库公开”当作已授予任意使用和再分发许可。
这不是代用户选择 MIT/Apache，也不要求购买认证。
依据：[GitHub licensing](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。

提供简短的缺陷反馈、贡献和安全问题报告入口及支持版本说明。可复用 README/Issues，
不强制拆成多份空模板。建议 SECURITY.md 指向真实可用的非公开报告方式，不预填未经同意的邮箱或响应 SLA。
依据：[GitHub security policy](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/add-security-policy)。

### 3.2 唯一版本、精确源码与兼容性 — W6 / W7C

**建议必需：** 明确唯一正式发布仓库；发行版本、CLI、Manifest、包元数据、tag 和 release notes 一致。
产品版本与协议版本分别说明；不要因为名称含 2.9 就自动将实现 0.2.0 升为 3.0。
从明确已提交版本的隔离检出构建，不将工作树中的未提交文件偷偷打入同版本发行物。

先定义用户依赖的公开接口：Codex 接入方式、CLI/JSON、生成物合同、状态兼容性及支持环境。
再决定版本号与破坏性变更说明。采用 SemVer 时，0.x 表示初期开发，已发布版本内容不得替换；
预发布标签说明不稳定性，不是用来绕过原有验收承诺。
依据：[Semantic Versioning 2.0.0](https://semver.org/)。

### 3.3 验收和交付同一份包 — W6 / W7A / W7B

**建议必需：** 保留已验发行附件，上传同一份内容；不要测试源码 A 后临时重打包 B 再称它已通过。
候选需变更时产生新候选并复验受影响部分。仅改变预发布标记不会运行测试；包内版本或文件变了仍应重核。
GitHub 自动源码 ZIP 不默认等于 Foundry 可用包；若将源码 ZIP 定义为正式载体，也必须从它独立完成接入和建设。

包内包含实际必需的指令、运行资源、公开样例、依赖说明与许可；从独立环境不能回读原开发仓库。
在已授权发布后的下载边界，核对实际附件与已验文件一致并做最小加载冒烟；不因下载就重跑全部昂贵模型案例。
复用 H1 的每归档一个摘要，不新增逐日志/逐回执/逐消息摘要或新签名网络。

若首发选择 Python 包，核对 pyproject 的依赖、Python 范围和许可元数据，并实际检查分发文件。
采用现代 license/license-files 表达时同步验证构建后端支持，不只追加字段；官方指南列出 setuptools
从 77.0.3 支持该形式。若选择便携项目目录，则只验该路线，不强制再做 PyPI、wheel、Plugin 等多套分发。
依据：[PyPA metadata](https://packaging.python.org/en/latest/specifications/pyproject-toml/)、
[PyPA writing pyproject](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)。

### 3.4 CI 绿灯必须对应实际验收 — W6 / W7C

**建议必需：** 发布判定明确检查当前候选的必要测试是否真正执行通过，不能仅看 workflow 总绿灯。
GitHub 的 required status check 可接受 success、skipped、neutral；因此必须由项目的发布结果汇总明确
拒绝必需项的 SKIP/NOT_RUN/BLOCKED。可选项单列，不把全部 opt-in 变成每轮强制项。
依据：[GitHub required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)。

**建议实现：** 一条精简 CI 跑公开源码回归、规范/Skill 检查及包资源/加载检查；真实模型与原生沙箱验收
在声明的受支持环境按候选里程碑执行并关联结果，不强制每个 PR 调用模型，也不将账户凭据传给外部 PR。
Linux 单测通过不代表 macOS 原生执行链通过。已有可靠本地入口可先复用，不为 CI 重写执行器。
分支必要状态检查、发布 tag 保护使用 GitHub 内置能力，不引入多名人工签字要求。
依据：[GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)。

### 3.5 版本内容不可变、说明面向用户 — W7C

**建议必需：** 已发布版本不移动 tag、不覆盖附件修补；缺陷修复发新版本。
release notes 说明新增/修复/不兼容项、已验宿主及模型环境、接入升级步骤、真实已验范围和限制，
并关联同候选测试证据。生成的 PR 列表可作为素材，不能代替用户能读懂的影响说明。
依据：[GitHub release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)、
[OpenSSF passing criteria](https://www.bestpractices.dev/en/criteria/0)。

**推荐机制，非额外认证门：** 采用 GitHub Immutable Releases。官方推荐先创建 Draft、补齐附件、再发布；
发布后锁定 tag 与附件，GitHub 自动生成 release attestation。标题/说明仍可编辑，不能称整页完全不可修改。
优先复用平台记录，不自己再造签名/证书链；本补充不启用任何远端设置。
依据：[GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)。

### 3.6 基本卫生与后续缺陷闭合 — W6 / W7C

**建议必需：** 检查拟公开源码及附件不含有效凭据、私有 PRD、用户数据、旧运行库或私有路径依赖；
复核实际发行依赖的已知可利用问题，发现真实问题就修复/阻止对应发布。扫描不可用不写成已检查通过。
若发现真实凭据泄露，先处置并由用户授权相关外部操作，不自动重写 Git 历史。

保留可复现缺陷→归属→修复→回归→受影响发行版本的单一记录；公布受支持升级/回退方式。
回退程序不意味着可以降级读取新格式数据库，更不撤销已经发生的副作用。不需要新建工单平台。
OpenSSF 的许可、可运行测试、用户反馈、release notes 与不泄露凭据可作为实践参考；
不以获得徽章、分数或全套认证为 Foundry 本轮发布前置。见 [OpenSSF criteria](https://www.bestpractices.dev/en/criteria/0)。

## 4. 对原工作包的补充，不增加串行审批

| 现有包 | 本次明确补齐的内容 | 完成依据 |
|---|---|---|
| W6 | 许可/第三方声明、唯一接入方式、依赖/支持矩阵、发行构建及精简 CI | 实际候选包含必需资源，公开步骤可执行；所选许可得到用户明确决定 |
| W7A/W7B | 从同一个发行候选完成新建/既有工程验收 | 独立环境实际建设、使用及行为结果，不借原工作区 |
| W7C | 发布结果汇总不吞 SKIP、版本/tag/附件一致、说明/缺陷/升级闭合 | 已验候选与待发布附件相同，范围内已知缺陷关闭 |

此前 M1 的真实结果保留；不得仅为符合文件命名或取得绿色标记重跑已无疑点的同版本证据。
专项剔除、必要恢复与计划适应能力仍按原 W1/W4/W5 处理，不能被本次 GitHub 分发补充遮盖。

## 5. 推荐发布顺序与结束条件

完成原计划剩余工程 → 确定版本/来源提交并构建候选 → 源码与包检查 → 同包双案例/独立接入
→ 准备可读 release notes 与附件 → 获准后 Draft/上传/发布 → 下载身份与最小加载核对。

准备说明和本地验证不需要逐包批准；新案例仍先展示搭建文档并取得人类确认，实际模型/路径/预算仍需
具体范围批准。GitHub 设置修改、上传 Draft/附件、推送及正式发布沿用真实授权边界，不能从“检索补充”推导。
可在一次充分展示的发布授权中覆盖约定动作，不增设重复人工按钮。

不增加强制多平台、SBOM 全家桶、SLSA 高等级、外部审计、全量模糊测试、每个提交双人批准或第三方试用。
这些只有明确消费者要求或实际风险时另评估；不会用“可选”豁免已明确约定的隔离、授权、基本身份和功能验收。
原发布门与上述适用项完成后结束本轮，不以无限泛化 Review 作为完成条件。
