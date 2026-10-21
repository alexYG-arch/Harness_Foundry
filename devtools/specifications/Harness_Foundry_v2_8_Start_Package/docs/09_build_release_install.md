# 09｜构建、发布、认证与安装

## 1. 目的

本文件给出 Main Harness Build Project、Foundry Conformance Lab、Conformance Linkage Review 三个工程从搭建到联通、修复、认证和真实安装的唯一有向流程，消除 Pack、Artifact、Certificate 和 Release Lock 的循环依赖。

前置规范：

- [阶段状态机](./04_phase_state_machine.md)
- [Workpack 与执行模式](./05_workpack_and_execution_modes.md)
- [Agent 与 Runtime 权责](./06_agent_and_runtime_ownership.md)
- [Conformance 架构](./08_conformance_architecture.md)
- [联通修复与失效](./10_linkage_repair_and_invalidation.md)

## 2. 三个工程的固定责任

| 工程 | 产出 | 不负责 |
| --- | --- | --- |
| Main Harness Build Project | Charter Start 执行包、Candidate、Release Artifact、Harness-specific Pack 声明 | 独立签证、修改 Lab Checker |
| Foundry Conformance Lab | Runner Attestation 校验、正/负/篡改测试、Certificate/Findings | 修复 Harness、真实安装 |
| Conformance Linkage Review | 只读 A/B0/B1/C/D 联通报告、Repair Route | 安装、修复、最终发证 |

Harness-specific Conformance Pack 是声明式认证资产，不是第四个可执行校验器。权威 Checker 只存在于 Lab；Linkage 只验证映射和绑定。

## 3. 工程搭建顺序

搭建顺序固定为：

1. 以 `AUTHORING_ONLY` 生成整个目标 Foundry Program Start Package Candidate，其中包含三个工程各自的 Start Package 和机器 DAG，然后停止；
2. Human Gate 审阅并批准 Charter/Profile/三工程方案，形成共享 Protocol、Schema、ID Namespace 与兼容矩阵 Lock，并以 `REGISTRATION_ONLY` 登记控制平面；
3. 创建、自校验并发布 Foundry Conformance Lab 工程及独立不可变 Lab CLI；
4. 创建、自校验并发布 Conformance Linkage Review 工程及独立只读 Linkage CLI；
5. 从已批准目标包物化并验证 Main Harness Build Execution Package；
6. 以 `REGISTRATION_ONLY` 将 Main Program 登记到目标 Build Project；
7. 由 Build Program Driver 按 G0→P1→P2→P3→P4 逐锁执行。

第 1 步不能执行任何工程 Workpack；第 2 步 Registration 不等于安装。第 3、4 步安装的是独立校验工具，不是最终 Harness。

该顺序必须实例化为 `ENGINEERING_PROJECT_DAG.json`；每个节点声明 owner project、mode、predecessors、Command IDs、expected outputs、readiness predicate、failure transition 和 invalidation set。编号文本本身不能供 Driver 自动推进。

## 4. 无循环依赖的发布链

```text
P4 local closure
-> P4_BUILD_INPUT_LOCK
-> Pack Draft
-> Linkage A: Interface Completeness
-> Linkage B0: Normative Pack Binding
-> Linkage C: Evidence Compatibility
-> immutable Artifact Build
-> Linkage B1: Artifact Pack Binding
-> P4 Installability Environment
-> P4_RELEASE_CANDIDATE_LOCK
-> single Certification Environment install
-> Linkage D: Installed Handshake
-> Lab Installed Certification + C4
-> Conformance Certificate
-> P4_CERTIFIED_RELEASE_LOCK
-> explicit Real Target Install Authorization
-> Real Target Installation Receipt + Active Instance Manifest
```

禁止在 Artifact 构建前预填 Artifact Hash，也禁止在 Certificate 产生前预填 Certified Release Lock ID。

目标包必须把本链逐节点写入 `RELEASE_PIPELINE_MANIFEST.json`。不得将 A/B0/C/Artifact/B1/Installability/Candidate/Certification Install/D/C4 压缩成 `P4 -> C4` 两个机器状态。

## 5. Candidate Lock 与 Certified Lock 分离

### 5.1 `P4_BUILD_INPUT_LOCK`

由 P4 本地 Integration/Build Input Gate 产生，只绑定可构建源码、配置、依赖锁、Charter/Profile、前驱 Lock 与证据。此时 C4 尚不可执行；该 Lock 不声明 Artifact 已构建、Harness 可安装或 Release 已认证。

### 5.2 `P4_RELEASE_CANDIDATE_LOCK`

在 Artifact、B1 和 P4 Installability 全部通过后产生，至少绑定：

- `P4_BUILD_INPUT_LOCK` Hash；
- Artifact identity、distribution/version、内容 Hash；
- Pack B0/B1 Report Hash；
- P4 Installability Receipt 与 installed-origin evidence；
- Lab/Linkage 工具版本和待执行认证计划。

Candidate Lock 只授权进入认证环境，不授权真实目标安装。

### 5.3 `P4_CERTIFIED_RELEASE_LOCK`

仅在唯一认证环境的 Linkage D、Lab 正向/负向/篡改测试、外部 C4 与 Certificate 全部通过后产生，绑定 Candidate Lock、C4 Report、Certificate、全部 Attestation、安装来源证据和失效策略。只有该 Lock 可令 `release_ready=true`。

三个 Lock 必须是不同 Schema/ID；不得把同一个 `P4_RELEASE_LOCK` 在流程中反复补字段。

## 6. Linkage Preflight A/B0/C 与制品绑定 B1

### A：Interface Completeness（构建前）

A 只读校验 Main Build Project 是否完整提供 Protocol 要求的 Conformance Interface、证据 emitter、Stage/Run Path 标识、安装入口声明和 Repair Route。A PASS 不证明 Pack 已绑定，也不证明 Harness 已实现。

### B0：规范绑定（构建前）

B0 校验 Pack Draft 是否绑定：

- Protocol/Schema/Charter/Profile/P4 Build Input；
- Canonical Intent/Normative Atom；
- Stage、Run Path、Scenario、Checker ID；
- Runtime ownership、Trusted Attestation 要求；
- 必需正向、负向、篡改与来源检查。

B0 时 `release_binding.status` 必须为 `PENDING_ARTIFACT`；Artifact Hash、Candidate Lock、Certificate 和 Certified Lock 字段必须不存在，而不是伪造占位值。

### C：Evidence Compatibility（构建前）

C 校验 Pack 请求的每类证据是否有 Main Harness emitter、Schema、读取路径、场景入口、Checker consumer 与失败语义。C 只验证形状和连接兼容性，不把预生成 fixture 或计划文件当作真实运行证据。

### B1：制品绑定（构建后）

B1 只在不可变 Artifact 生成后执行，并把 Pack Release Binding 绑定到：

- Artifact Hash、distribution/version、build provenance；
- `P4_BUILD_INPUT_LOCK`；
- B0 Report Hash；
- 预期安装入口与 module/distribution mapping；
- 本轮 Candidate identity。

固定顺序是 `Pack Draft -> A -> B0 -> C -> Artifact -> B1`。Candidate Lock 引用 B1；B1 不反向引用尚未产生的 Candidate Lock。Certificate 引用 Candidate Lock；Certified Lock 再引用 Certificate，由此保持有向无环。

## 7. 三个环境与唯一安装 Owner

所有创建环境、安装、卸载、升级和清理动作的唯一 Owner 是 `Certification Installer`。Lab、Linkage、Coding Agent 和 Final Runtime 均不得代行。

| 环境 | 用途 | 生命周期与规则 |
| --- | --- | --- |
| P4 Installability Env | 证明 Artifact 能从零安装、启动、卸载 | 临时、隔离；可按独立 Workpack 重建 |
| Single Certification Env | 对一个 Candidate 进行唯一权威认证 | 每次尝试新建；只安装一次；失败后销毁，不就地修复 |
| Real Target Env | 应用已认证 Release | 必须独立授权；不得复用前两个环境 |

认证环境的“single”表示一个 Certification Attempt 只有一个 canonical environment ID 和一次 Candidate 安装。不同目录中的多次安装、先 editable 后 wheel、失败后覆盖安装，都会使该 Attempt 无效。

## 8. 安装与入口来源校验

P4、认证和真实目标安装都必须从不可变 Artifact 安装，不得从 Start Package、Build Execution Package 或源码树运行。至少验证：

1. 解释器/Runtime 和 Harness CLI 使用绝对路径，且 `realpath` 位于目标环境；
2. CLI 文件 Hash、distribution、version 与 Candidate Lock 一致；
3. 适用时，import module 的 `__file__`/origin 位于目标环境的已安装分发目录；
4. Python 分发的安装不是 editable，`direct_url.json` 不含 editable 标志；其他 Runtime 执行等价的链接/工作区安装检查；
5. Python Harness 的 `PYTHONPATH` 为空或受控，源码根与执行包根不在 `sys.path`；其他 Runtime 检查等价的 module/package search path；
6. CWD 位于独立 Runtime Workspace，不在 repo、Start Package 或 Build Program 目录；
7. PATH 中同名命令不会 shadow 绝对入口；
8. console entry point 指向 Final Harness Runtime，不指向 Build Program Driver；
9. 父进程、入口 Hash、Artifact Hash 和 Runtime Trace 可闭合；
10. `source_tree_on_sys_path=false` 与 `editable_install=false`（或 Runtime 等价字段）有独立 readback 证据。

必须生成 `installed_target_descriptor.json`，包含环境 ID、Artifact、绝对 executable、realpath/hash、distribution/module origin、CWD/PATH/module search path 摘要、`entrypoint_kind=FINAL_HARNESS_RUNTIME` 和 `build_program_assets_loaded=false`。发现任何源码回退返回 `INSTALLED_ENTRYPOINT_ORIGIN_MISMATCH`。

## 9. P4 Installability

P4 Installability 是 Candidate 形成前的发布 Gate，不是最终认证。Certification Installer 必须在全新临时环境中：

```text
create isolated environment
-> install exact immutable Artifact
-> verify distribution and absolute entrypoint origin
-> run smoke/startup/help/version checks
-> run minimal Final Harness handshake
-> uninstall and verify cleanup when required
-> seal receipt and destroy environment
```

执行必须使用结构化 argv Command Manifest；以上文本不是可执行命令。P4 环境成功不能替代 Single Certification Env，也不能产出 Certificate。

## 10. 单一认证执行

Candidate Lock 有效后：

1. Certification Installer 创建新的 canonical certification environment；
2. 使用绝对工具入口安装 Candidate Artifact 一次；
3. 写入 Installation Receipt 和 Installed Target Descriptor；
4. Linkage 以只读方式执行 D：Installed Runtime Handshake；
5. Lab 发出 nonce，由 Trusted Runner 执行需要 Codex/LLM 的 Stage；
6. Lab 运行正向、负向、篡改、重放、来源和细节保真检查，并生成外部 C4 Report；
7. Linkage/Lab Finding 均指向 owner Phase/Workpack；
8. C4 PASS 后签发 Certificate，再生成 Certified Release Lock；
9. 密封并保留证据，认证环境不得转成真实目标环境。

任一失败都使本次 Attempt 终止。不得在认证环境中改代码、换包、补文件、覆盖安装或手工修 receipt 后重跑。

## 11. 联通与校验失败的修复闭环

```text
Finding
-> classify owner Phase / Outcome / Workpack
-> invalidate dependent locks, B0/B1, Artifact, Candidate and Certificate
-> create bounded Repair Workpack in Main Build Project
-> rebuild affected phase chain
-> regenerate Pack Draft and rerun A/B0/C
-> rebuild immutable Artifact
-> rerun B1 and P4 Installability
-> create new Candidate Lock
-> create a new Certification Environment
-> rerun Linkage D, Lab and C4
```

Lab 与 Linkage 不得直接修 Pack 或 Harness 以“让校验通过”。若问题属于共享 Protocol/Checker，则先修复对应独立工程、发布新工具版本，并使引用旧版本的认证计划失效。

## 12. 真实目标安装

真实安装必须同时具备：

- 有效 `P4_CERTIFIED_RELEASE_LOCK`；
- 与 Lock 完全一致的 Artifact Hash；
- 明确目标、窗口、回滚和副作用边界的 Install Authorization；
- Certification Installer 的结构化命令授权；
- 目标环境预检与备份/回滚准备。

安装后必须重新执行绝对入口、非 editable、module origin、source shadowing 和 Final Runtime Handshake 检查，并生成：

- `real_target_installation_receipt.json`；
- `active_instance_manifest.json`；
- `installed_target_descriptor.json`；
- post-install readback 与回滚状态。

真实环境 Receipt 证明“已应用”，不反向修改 Certificate；如目标差异超出认证兼容矩阵，应阻断安装或启动新的目标特定认证，而不是把差异写成豁免备注。

Program Driver 不得从普通 Build/Certification Authorization 继承真实安装权限。即使 Certified Lock 有效，也必须停在 `WAITING_REAL_TARGET_INSTALL_AUTHORIZATION`；只有目标、窗口、回滚和命令均绑定的独立授权实例才允许进入该模式。

## 13. 明确禁止

- 在 Build Program Authoring/Registration 阶段安装或运行 Harness；
- 从执行包目录调用最终 Harness；
- P1/P2/P4 先做、P3 以后补；
- 用 P3 空目录代替 `P3_NOT_APPLICABLE_LOCK`；
- 让 P4、Lab 和 Linkage 分别安装不同 Candidate；
- 使用 editable install、repo script、相对 CLI 或污染的 `PYTHONPATH` 做认证；
- 把 P4 Installability PASS 写成 Conformance PASS；
- 把 Candidate Lock 用于真实目标安装；
- 在失败认证环境中原地修复后继续发证。
