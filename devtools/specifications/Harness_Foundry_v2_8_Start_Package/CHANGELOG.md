# Changelog

## v2.8

### 受控自动推进

- 保留 `AUTHORING_ONLY -> HUMAN_REVIEW` 硬停点，禁止生成后自启动。
- 增加批准后的 `CONTROLLED_AUTO_PROGRESS` 语义；Driver 只能在有效授权、唯一下一动作和有界副作用内推进。
- 自动推进遇到授权扩大、设计权威决定、P3 N/A、循环振荡、凭据缺失或真实目标安装时必须停止。

### 三工程控制平面

- 增加 Main Build、External Lab、Read-only Linkage 的机器 Program Manifest、工程 DAG、状态和 readiness barrier。
- 增加三个工程各自的 Charter、Workpack、Command、Build/Install Plan 模板。
- 明确共享 Protocol/Schema Lock、工具版本兼容和跨工程失效传播。

### Driver、发布与恢复

- 增加 Program Driver Contract/State、Automation Policy、Authorization Policy 和 Execution Authorization。
- 将 A/B0/C/Artifact/B1/Installability/Candidate/Certification Install/D/C4 全部写入机器发布流水线。
- 增加 Workpack Result、Promotion Ledger、Loop Policy/State、Finding、Repair Routing、Invalidation DAG、Reentry Plan 和 Revocation Ledger。
- 定义 next-action 选择、单 Workpack lease、幂等键、原子状态提交、断点恢复、最大轮数和振荡升级。

### 模板一致性与验收

- 补全 `PROGRAM_STATE` 的 current/next phase、有效/失效锁和 blocker 字段。
- 修正 Command Manifest，要求绝对 executable、Authorization、期望退出码和输出证据。
- 扩展机器角色表，加入 Driver、Trusted Runner、Certification Installer 和 Human Gate Owner。
- 增加标准库 Validator 与负向测试，防止缺少自动化资产时仍出现 authoring 假绿。

## v2.7

### 版本定位修正

- 将本包明确定义为 documentation-only authoring guide。
- 本包只指导模型生成目标特定的初始宪章 Start Execution Package。
- 不再把方案文档目录表述为已实现的 Harness、Conformance Package、校验器或安装包。
- 明确目标包完成只代表 authoring 产物可审阅，不代表工程、运行、安装或认证完成。

### 文档拆分

- 将大体积协议拆为入口、权威、调整、authoring、阶段、Workpack、Runtime、意图保真、Conformance、安装、联通和验收等小主题。
- 增加 DOC_INDEX，支持按用户任务加载最小文档集。
- 要求跨文档只使用相对链接，规则正文只保留一个权威来源。
- 将机器状态、清单和映射放入 JSON，不继续堆入单个 Markdown。

### 用户调整能力

- 允许用户按 Agent/Harness 类型、技术栈、阶段、目录、风险和交付形态调整目标方案。
- 增加参数化、结构适配、不变量影响和表达调整四类处理。
- 要求所有 adjustment、assumption、deviation 和 approval 可追踪。
- 明确合理调整不能静默删除 authoring/execution 隔离、阶段前驱、细节保真、真实 Runtime 证据或独立认证。

### Authoring 与 Execution 隔离

- BUILD_PROGRAM_AUTHORING 活动固定使用 AUTHORING_ONLY 执行模式。
- 规定 generated commands are data。
- Authoring 完成后强制 AUTHORING_STOP。
- Build Program Registration 仅装载状态且 auto-start=false，不得被称为安装或自动启动。
- Coding、package build、isolated install、real install 和 certification 均需要独立模式与授权。

### 目标 Start Package 契约

- 增加 Program Charter、Target Profile、Start Context、Authority Boundary、Intent、Phase State、Contract、Workpack、Capsule 和 Handoff 的必需语义角色。
- 增加 artifact map，允许用户调整文件名而不丢失规范角色。
- 初始 Program State 同时记录 highest_touched_phase 与 highest_locally_closed_phase。
- 首个 Workpack 默认用于 G0 或等效控制基础，并保持未执行。

### 阶段顺序修正

- 将阶段顺序从建议文本升级为显式状态机。
- 下一阶段必须引用有效前驱 Lock。
- 禁止 P1/P2/P4 已触达而静默跳过 P3。
- 不适用阶段必须产生有理由、批准和等效证明的 N/A Lock。
- 上游变化触发下游 Lock、Artifact、Pack、Certificate 和安装状态的必要失效。

### Intent Fidelity 修正

- 增加 Canonical Intent、Intent Atom 与 Coverage Matrix。
- 要求保留否定、条件、顺序、阈值、单位、默认值、错误、取消、重试、超时、权限和恢复分支。
- Catalog 自身不完整时不得通过“catalog 覆盖率 100%”伪装完整。
- 要求删除细节、反转否定、修改单位/顺序等负向 mutation tests。

### Agent 与 Runtime 证据修正

- 区分模型/Agent 规划者、Coding Agent、Program Driver、Primary Runtime、External Tool Runtime 和 witness。
- 自报 executor_type、session_ref 和 SHA256 不再足以证明真实 Codex 或目标 Runtime 被调用。
- 要求 Lab-owned challenge、独立 invocation witness、反重放和输入输出绑定。
- 无可信证明时使用 INVOCATION_UNVERIFIED，不得 PASS。

### 三工程权责修正

- 主 Harness Build Project 只负责建设、打包和被测 evidence emitters。
- Foundry Conformance Lab 独立执行认证，不修改被测 Harness。
- Conformance Linkage Review 只读检查接口、Pack、证据、installed handshake 和 repair route，不签发认证。
- Harness-specific Conformance Pack 是声明式认证资产，不是第四个自执行校验器。

### Build、Pack、Release 与 Install 顺序修正

- 将 Pack Binding 拆为构建前的 B0 规范绑定和构建后的 B1 Artifact 绑定。
- 将单一 P4 Release Lock 拆为 P4_RELEASE_CANDIDATE_LOCK 和 P4_CERTIFIED_RELEASE_LOCK。
- 推荐锁链为：

~~~text
P4_BUILD_INPUT_LOCK
→ B0
→ Release Artifact
→ B1
→ P4 Installability
→ P4_RELEASE_CANDIDATE_LOCK
→ 单一认证环境 / Certificate
→ P4_CERTIFIED_RELEASE_LOCK
~~~

- 真实目标安装只允许在认证后另行授权。

### 安装入口修正

- 要求 installed target descriptor 绑定 distribution、version、artifact hash、Python/CLI realpath、import origin、CWD、PATH、PYTHONPATH 和 site-packages。
- 认证环境必须位于源码与执行包目录之外。
- 禁止 editable import、PATH shadow、repo script 或 Build Program Driver 冒充 installed Harness。

### 验收与声明修正

- 拆分 authoring structural check、coding validation、Runtime verification、Linkage Review、external Conformance 和 Human Review。
- 每条 MUST 必须有 machine、human 或 hybrid 验证。
- 正向场景之外必须有 false-success、tamper、replay、origin mismatch、phase skip 和 detail-loss 负向场景。
- 统一禁止用局部 PASS、样例 PASS 或计划完成宣称系统、安装、发布或认证 PASS。

## v2.7 与 v2.6 的兼容边界

- v2.7 保留 v2.6 中有价值的 Constitution、Charter、Workpack、Evidence、Review–Fix 和独立认证思想。
- v2.7 不把 v2.6 大文件作为默认第二事实源。
- 迁移必须通过[MIGRATION_MAP_v2_6_to_v2_7](MIGRATION_MAP_v2_6_to_v2_7.md)记录概念、路径和状态差异。
- 仅改目录名或版本号不构成迁移完成。
