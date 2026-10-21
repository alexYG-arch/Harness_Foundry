# 08｜三工程校验架构与信任边界

> 状态：目标工程架构规范，不是现状声明。本包只指导模型生成新的 Agent/Harness 宪章 Start 执行包；除非目标工程随后完成 coding、安装与认证，否则不得声称 Main Build、External Lab、Linkage、checker、attestation 或 Certificate 已存在。

## 1. 架构目标

生成的目标包必须把“建设”“权威校验”“只读联通审查”分成三个独立工程，并把 Harness-specific Conformance Pack 限定为声明式数据。

```text
Main Harness Build Project
    │ 产出接口、Pack Draft、Harness Artifact、runtime evidence
    ▼
Read-only Conformance Linkage Review
    │ 只读证明规范链/证据链/执行链/修复链是否接通
    ▼
External Foundry Conformance Lab
       独立运行 checker、attestation、负向/篡改测试并决定 C0-C4
```

工程顺序和安装要求见[构建、发布与安装](09_build_release_install.md)，阶段前驱见[阶段状态机](04_phase_state_machine.md)。

## 2. 三工程职责

### 2.1 Main Harness Build Project

负责：

- 生成并维护目标 Charter、Intent Atom、Workpack DAG、StageSpec 和 Run Path；
- 按合法阶段转换执行 coding；
- 实现 Harness runtime、evidence emitter 和公开 conformance interface；
- 生成声明式 Conformance Pack Draft；
- 构建不可变 release artifact；
- 接收 finding，并在唯一 owner Workpack 中修复后重建。

不得：

- 自行签发或判定 External Conformance Certificate；
- 把内部 unit test、Pack parser PASS 或自己的 receipt 当成 C4 PASS；
- 为通过校验而修改 External Lab 的权威 checker；
- 在最终运行时回到 Build Driver、源码脚本或执行包入口。

### 2.2 External Foundry Conformance Lab

它必须是独立可安装、可版本化的工程，运行在受控认证环境中。

负责：

- 拥有权威 checker 实现、scenario runner 和判断规则；
- 生成 challenge、独立观察真实运行并形成 Lab-owned attestation；
- 校验 Pack 声明、Harness evidence、安装来源和 release binding；
- 运行正向、负向和篡改场景；
- 输出 finding，或在全部门禁通过后签发绑定 Hash 的 Certificate；
- 记录 checker distribution/version/hash 与认证环境指纹。

不得：

- 使用被认证项目自带 checker 作为最终权威；
- 静默修复 Main Build 或 Pack；
- 仅因 receipt 自洽、schema 合法或字段写有 `executor_type=codex` 就认可真实调用；
- 在无法确认调用来源时降级为 PASS。

### 2.3 Read-only Conformance Linkage Review

它是独立的只读审查工程。

负责：

- 执行 A、B0、C、B1、D 联通门禁；
- 对照接口、Pack、schema、fixture、evidence、checker contract 和 repair route；
- 输出结构化 report、finding 和建议的唯一 repair owner；
- 阻断未接通的候选进入外部 C4。

不得：

- 安装或修改 Harness；
- 修改 Pack、Lab checker、Lock 或 evidence；
- 直接执行修复；
- 签发 Certificate；
- 把 Linkage PASS 表述成 Conformance PASS。

Linkage 工具自身的缺陷必须回到 Linkage 工程的维护 Workpack；其他缺陷按[修复与失效传播](10_linkage_repair_and_invalidation.md)回流。

## 3. Conformance Pack 只是声明式数据

每个目标 Harness 可以有 Harness-specific Conformance Pack，但 Pack 只能包含：

```text
manifest 与 schema 版本
当前 canonical baseline / Charter / Workpack / StageSpec / Run Path Hash
release binding 状态；B0 时无 Artifact Hash，B1 后才有最终 Hash
scenario declarations 与 fixture references
expected receipt / trace / ledger declarations
intent atom 与 checker assertion mapping
supported profiles
repair routing metadata
```

Pack 不得包含或动态加载：

- 决定 PASS/FAIL 的可执行 checker；
- 可替换 Lab checker 的脚本、插件或表达式；
- 自签名 Certificate 或预填 PASS；
- 修改 Harness、Lab、Linkage 环境的 hook；
- 认证凭据、Lab 私钥或可复用 challenge。

Pack parser 只负责 schema 校验、解码和受限规范化。parser 输出属于“被检查的数据”，不是权威判断。最终 assertion 必须由 External Lab distribution 中受版本和 Hash 约束的 checker 执行。

若 Pack 携带可执行判断逻辑，必须返回 `EXECUTABLE_PACK_FORBIDDEN`；若 Certificate 只绑定 parser/Pack 而未绑定 Lab checker Hash，必须返回 `AUTHORITY_BINDING_INCOMPLETE`。

## 4. Lab-owned Trusted Runner Attestation

Harness 生成的 runtime receipt 是自报的待验证声明，单独存在不足以证明真实调用。要证明调用的是 Codex 而不是 Python 伪造字段，Lab 必须拥有由其发起 nonce 并控制策略的独立 Trusted Runner Attestation 链。

### 4.1 Challenge 与观察

每次场景开始前，Lab runner 必须生成一次性 challenge：

```text
challenge_id
nonce
scenario_id
run_id
expected_stage_id
issued_at / expires_at
lab_instance_id
```

Lab 必须独立观察并记录：

```text
实际 executable / endpoint 标识
executable realpath、version、binary 或 distribution hash
process lineage 或等价 provider invocation identity
request/session/invocation ID
challenge 与 request/input hash 的绑定
start/end event、exit status
raw event stream hash
output hash
environment fingerprint
```

不要求假设 Codex 本身一定提供密码学签名；但 Lab 必须持有至少一种被认证项目无法自行伪造的独立观察来源。没有独立观察时结果只能是 `INVOCATION_UNVERIFIED`。

### 4.2 关联与封存

Lab checker 必须同时关联：

```text
challenge
Lab observation
Harness receipt
intermediate receipts
final output
installed artifact hash
scenario and intent atom IDs
```

并拒绝：

- Python 写出的自洽假 receipt；
- 其他 run、stage、artifact 或 challenge 的 receipt replay；
- 合法调用后替换 output；
- 只有 final receipt、缺少必需中间 receipt；
- receipt 时间线、父子链或 input/output Hash 不连续。

Attestation 必须由 Lab-owned key 或等价受控完整性机制封存，并记录 verifier/checker Hash。认证目标不得拥有生成有效 Lab attestation 的凭据。

## 5. 权威顺序

发生冲突时按以下顺序处理：

```text
用户批准的 Canonical Intent Baseline
→ Target Charter / Protocol Lock
→ External Lab 的公开 checker contract 与锁定实现
→ Main Build 的 conformance interface
→ 声明式 Conformance Pack
→ Harness 自报 receipt / report
```

低层输出不得覆盖高层规范。Linkage report 只能指出冲突，不能改变权威顺序。

## 6. 联通与认证门禁

`C0-C4` 是 External Lab 的阻断式认证轨道。P4 本地 Integration/Build Input Gate 只生成 `P4_BUILD_INPUT_LOCK`，此时 C4 尚不可执行。后续门禁必须按以下顺序运行，不能把构建后事实预填到构建前 Pack：

### Gate A — Interface Completeness

检查 Main Build 是否声明完整：canonical baseline、outcome/atom catalog、Workpack DAG、phase locks、`P4_BUILD_INPUT_LOCK`、Run Path、runtime ownership、receipt matrix、repair route、certification checkpoints。

### Gate B0 — Pre-build Normative Binding

在 Artifact 尚未生成前，检查 Pack Draft 是否绑定当前 Canonical Intent、Charter、Workpack DAG、StageSpec、Run Path 和 receipt matrix Hash。此时 `release_binding.status` 必须为 `PENDING_ARTIFACT`，Artifact Hash、Candidate Lock、Certificate 和 Certified Lock 字段必须不存在，不得编造占位值。

### Gate C — Evidence Compatibility

使用 schema 与正/负 fixtures 只读验证 Harness emitter 契约、Pack 声明和 Lab checker contract 是否兼容；必须证明非法 receipt 会被拒绝。Gate C 不证明安装后 runtime 已真实执行。

### Artifact Build

只有 A、B0、C PASS 且当前 `P4_BUILD_INPUT_LOCK` 有效时，Main Build 才能构建不可变 release artifact。构建规则见[构建、发布与安装](09_build_release_install.md)。

### Gate B1 — Post-build Artifact Binding

将 Pack Release Binding 绑定到真实 Artifact Hash、build provenance、`P4_BUILD_INPUT_LOCK` 和 B0 Report Hash。B1 必须重新检查 B0 的规范 Hash 未漂移；随后由 Candidate Lock 引用 B1，B1 不得反向引用尚未生成的 Candidate Lock。

### P4 Installability 与 Candidate Lock

Certification Installer 在一次性 P4 Installability Environment 中从不可变 Artifact 做干净安装、入口来源和最小启动检查。Artifact、B1 与 Installability 全部通过后，才生成 `P4_RELEASE_CANDIDATE_LOCK`；Candidate Lock 只授权进入唯一认证环境。

### Gate D — Installed Handshake

由只读 Linkage 在独立安装完成后检查：安装目标可发现、入口来自被认证环境、Pack 可加载、证据可被 Lab 读取、finding 可路由。D PASS 仍不是 Certificate。

### C4 — External Installed E2E Certification

由 External Lab 对唯一认证环境中的已安装 Artifact 执行完整正向、负向、篡改和来源校验。只有 C4 PASS 才可签发 Certificate，再生成绑定 Candidate + Artifact + Pack + checker + C4 Report + Certificate Hash 的 `P4_CERTIFIED_RELEASE_LOCK`。

```text
P4 local closure → P4_BUILD_INPUT_LOCK → Pack Draft
→ A → B0 → C → Artifact Build → B1
→ P4 Installability → P4_RELEASE_CANDIDATE_LOCK
→ Single Certification Environment Install → D
→ Lab Installed Certification + C4 → Certificate → P4_CERTIFIED_RELEASE_LOCK
```

任一步 FAIL 都按[修复与失效传播](10_linkage_repair_and_invalidation.md)回流；不得在失败点手改 evidence 后继续。

## 7. 目标 Start 包的架构验收

目标包至少必须生成：

- 三个工程各自的 Charter、owner、read/write 边界和安装说明；
- 声明式 Pack schema 与 `no executable logic` validator 任务；
- Lab checker registry、attestation contract 和 challenge/replay 规则；
- P4 Build Input、A/B0/C/Build/B1/P4 Installability/Candidate/D/C4 的输入、命令占位、输出和失败码；
- 单一 repair owner 与 invalidation graph；
- [强制负向与篡改测试矩阵](11_acceptance_and_negative_tests.md)。
- 三工程各自的 Project Start Package、机器状态、bootstrap/build/install Workpack；
- `THREE_PROJECT_PROGRAM_MANIFEST`、`ENGINEERING_PROJECT_DAG` 和跨工程 readiness barrier；
- 版本兼容、stale propagation、partial failure 和重新进入规则。

仅写出上述章节不代表工程已实现。只有对应文件、代码、测试、安装证据和 Lab readback 存在时，目标工程才能按自身状态机提升状态。

三工程的机器搭建顺序见[三工程机器 DAG](14_three_project_program_dag.md)。Program Driver 只协调状态，不改变本文件定义的三个权威边界。
