# 11｜目标包验收与强制负向/篡改测试

> 状态：验收设计规范，不是测试报告。本文中的测试 ID、命令语义和期望结果用于指导模型生成目标 Agent/Harness 的 Start 执行包与后续 coding Workpack；在真实测试、证据和 External Lab readback 产生前，所有结果均为 `NOT_RUN`。

## 1. 两层验收，禁止混写

### 1.1 Start 执行包验收

证明生成的目标 Start 包已经给工程 coding 提供足够明确的：

- 宪章、边界、Canonical Intent 与 Atom 追溯；
- P1→P2→P3→P4 不可跳跃状态机；
- Main Build、External Lab、Read-only Linkage 三工程搭建顺序和职责；
- P4 Build Input Lock→Pack Draft→A→B0→C→Build→B1→P4 Installability→Candidate→认证安装→D→C4 指令契约；
- 安装来源隔离、Lab attestation、finding/repair/invalidation 规则；
- 正向、负向和篡改测试 Workpack。

该层 PASS 只表示“目标工程可以按包开始 coding”，不表示 Harness 已实现、已安装或已认证。

### 1.2 Installed Harness C4 验收

证明一个确定的、不可变的已安装 Artifact 在 External Lab 中通过全部权威 checker 和强制测试，并生成绑定完整 Hash 集的 Certificate。

只有这一层可以声明 `C4_CERTIFIED`。Main Build 本地 Gate、unit test PASS、Linkage PASS、Pack parser PASS、fixture PASS 都不能替代它。

## 2. Start 包文档验收清单

目标 Start 包必须通过以下结构检查：

```text
AC-DOC-001  每项能力区分 REQUIRED / PLANNED / IMPLEMENTED / VERIFIED
AC-DOC-002  不把模板文字写成已存在实现
AC-DOC-003  所有生成文件、owner、前驱、命令、输出、证据路径明确
AC-DOC-004  canonical source 与 intent atom 有双向 coverage 契约
AC-DOC-005  三工程职责、读写边界与安装顺序明确
AC-DOC-006  Pack 被限定为声明式数据，parser 不是权威 checker
AC-DOC-007  Build Input/Pack/A/B0/C/Build/B1/Installability/Candidate/D/C4 无循环依赖
AC-DOC-008  P4 必须依赖当前有效的 P3 Lock 或获批 N/A Lock
AC-DOC-009  最终运行入口与 Build Driver/执行包入口分离
AC-DOC-010  finding 具有单一 owner 与可机读失效传播
AC-DOC-011  所有强制负向/篡改测试有实现 Workpack
AC-DOC-012  用户调整会触发 rebaseline、影响分析和下游失效
AC-DOC-013  三工程 DAG、Release Pipeline、Driver/Authorization/Loop 机器资产完整
AC-DOC-014  三工程均有独立 Start Package，真实目标安装保持独立硬授权
```

任何缺失均为 Start 包 BLOCKER，不得用“后续实现时再考虑”关闭。

## 3. 测试执行规则

1. 强制测试必须由 External Lab 的受控 runner 编排；Main Build 可预跑，但不能成为权威结果。
2. 每个测试必须从已知有效的 clean baseline 注入且只注入声明的 mutation。
3. 负向用例只有在系统拒绝错误、给出准确错误码、路由到唯一 owner 并使正确下游失效时才 PASS。
4. “命令报错”“进程崩溃”或“没有生成报告”不是合格拒绝。
5. 测试结果必须绑定 Artifact、Pack、checker、scenario set、environment 和 challenge Hash。
6. 所有结果默认 `NOT_RUN`；不得在 Start 包中预填 PASS。

## 4. 强制负向与篡改矩阵

| ID | 注入或篡改 | 必须观察到的拒绝 | Repair Owner / 失效范围 |
|---|---|---|---|
| NEG-RUN-001 | Python 直接生成字段和 Hash 自洽、声称 `executor_type=codex` 的 receipt；无 Lab 观察 | `INVOCATION_UNVERIFIED`；不能仅凭 schema/session ref PASS | Main Build；该 run、D/C4 evidence、Certificate |
| NEG-RUN-002 | 从旧 run、旧 challenge 或其他 stage 重放真实 Codex receipt | `RECEIPT_REPLAY_DETECTED` 或等价封闭码 | Main Build；当前 run 与 C4 |
| NEG-RUN-003 | 保留真实调用 receipt，但将 final output 换成另一文件 | `OUTPUT_ATTESTATION_MISMATCH` | Main Build；当前 run、Artifact 下游认证 |
| NEG-RUN-004 | 只提供 final success receipt，删除必需中间 stage/step receipt | `INTERMEDIATE_EVIDENCE_MISSING` | Main Build；当前 stage 与下游 Lock |
| NEG-RUN-005 | 用 plan、prompt、gate 文件冒充 runtime execution receipt | `NON_RUNTIME_ARTIFACT_REJECTED` | Main Build；当前 run 与 C4 |
| NEG-PHASE-001 | 构造 P1、P2、P4 Lock，完全跳过 P3 | `ILLEGAL_PHASE_TRANSITION` | Main Build；P4、Build Input、Artifact、Candidate、安装、D、C4 |
| NEG-PHASE-002 | P3 Lock 存在，但绑定旧 P2 Hash 或过期 baseline | `STALE_PREDECESSOR_LOCK` | Main Build；P3 及全部下游 |
| NEG-PHASE-003 | 用自然语言写“P3 不适用”，但无批准的 N/A Lock | `P3_NA_LOCK_MISSING` | Main Build；阻断 P4 |
| NEG-INST-001 | 安装环境通过 `PYTHONPATH`、editable install、PATH shadow 或 import fallback 加载源码/执行包 | `INSTALLED_ENTRYPOINT_ORIGIN_MISMATCH` | Main Build；安装、D、C4、Certificate |
| NEG-INST-002 | CLI 来自认证环境，但子进程回到 Build Program Driver | `RUNTIME_ROOT_OWNERSHIP_VIOLATION` | Main Build；安装与全部 runtime 证据 |
| NEG-INTENT-001 | 从 catalog 删除一个来源仍存在的 Intent Atom，并重算 catalog Hash | `SOURCE_TO_ATOM_COVERAGE_GAP` | Main Build；baseline 下游全部失效 |
| NEG-INTENT-002 | 把 `不得` 改成“建议不”、删除 `仅/除非` 或扩大否定作用域 | `INTENT_POLARITY_DISTORTED` | Main Build；受影响 Atom 及下游 |
| NEG-INTENT-003 | 删除/修改数值、单位、比较符或精度 | `INTENT_VALUE_OR_UNIT_DISTORTED` | Main Build；受影响 Atom 及下游 |
| NEG-INTENT-004 | 调换强制步骤，或把串行前驱改成可并行 | `INTENT_ORDER_DISTORTED` | Main Build；阶段/Run Path 下游 |
| NEG-INTENT-005 | 删除默认值、首次进入或重置行为 | `DEFAULT_BEHAVIOR_MISSING` | Main Build；相关实现、场景、证据 |
| NEG-INTENT-006 | 删除取消、重试、超时、错误恢复中的任一分支 | `REQUIRED_BRANCH_MISSING` | Main Build；相关实现、场景、证据 |
| NEG-INTENT-007 | 从已残缺的 Atom catalog 自算 100% coverage | `COVERAGE_DENOMINATOR_UNTRUSTED` | Main Build；coverage 与全部完成声明 |
| NEG-PACK-001 | 在 Pack 中嵌入可执行 checker，或让 parser 返回最终 PASS | `EXECUTABLE_PACK_FORBIDDEN` / `PACK_PARSER_NOT_AUTHORITY` | Main Build 或 Lab，按最早节点；B0/C 下游 |
| NEG-LAB-001 | 修改 checker 实现或规则集 Hash 后复用旧 Certificate | `CERTIFICATE_CHECKER_BINDING_MISMATCH` | External Lab；旧 C4、Certificate、Certified Lock |
| NEG-LAB-002 | 目标工程持有可生成有效 Lab attestation 的凭据 | `ATTESTATION_TRUST_BOUNDARY_BREACH` | External Lab；全部相关 attestation/Certificate |
| NEG-LINK-001 | Linkage Review 在发现失败后直接修改 Pack 或 Harness 再给 PASS | `READ_ONLY_BOUNDARY_VIOLATION` | Linkage Tool；该 report 无效，原 finding 保持 OPEN |
| NEG-BIND-001 | B0 预填不存在的 Artifact Hash，或 B1 未重验 B0 Hash | `PREMATURE_OR_STALE_ARTIFACT_BINDING` | Main Build；B0/B1 及下游 |
| NEG-CERT-001 | Linkage D PASS 被改写成 Conformance Certificate PASS | `CERTIFICATION_AUTHORITY_MISMATCH` | 声明产生方；Certificate/Release claim 无效 |
| NEG-AUTO-001 | 无、过期或 scope 不匹配的 Execution Authorization 仍请求执行 | `EXECUTION_NOT_AUTHORIZED` | Program Driver；不产生副作用 |
| NEG-AUTO-002 | 同一状态存在两个合法 next action 或两个 active Workpack | `AMBIGUOUS_NEXT_ACTION` / `MULTIPLE_ACTIVE_WORKPACKS` | Program Driver；保持原状态 |
| NEG-AUTO-003 | 命令已完成但状态提交前 Driver 崩溃，重启后再次执行副作用 | `IDEMPOTENCY_CONFLICT`，必须 readback/commit 而非重做 | Program Driver；当前 attempt |
| NEG-AUTO-004 | 相同 Finding 无进展重复，或状态 A↔B 振荡 | `LOOP_OSCILLATION_DETECTED` 并升级 | Repair Owner/Human Gate；loop 停止 |
| NEG-AUTO-005 | 普通 Workpack/Certification Authorization 请求真实目标安装 | `REAL_TARGET_INSTALL_AUTHORIZATION_REQUIRED` | Human Gate/Installer；不创建环境 |
| NEG-AUTO-006 | Lab/Linkage 工具版本不满足兼容矩阵仍解除 barrier | `PROJECT_COMPATIBILITY_BARRIER_FAILED` | 对应工具工程；下游保持等待 |
| NEG-AUTO-007 | 上游 Hash 已变化但跨工程状态仍显示 ready | `STALE_CROSS_PROJECT_STATE` | Program Driver；传播 invalidation |
| NEG-AUTO-008 | Repair 需要扩大写路径、联网、权限或改变 Canonical Intent | `AUTHORIZATION_SCOPE_EXPANSION_REQUIRED` | Human/Design Authority；停止自动 loop |

错误码可在目标工程中扩展，但必须保持一一可判定，不能全部折叠为 `VALIDATION_FAILED`。

## 5. 变异生成要求

Intent Fidelity 测试不得只靠人工列举。目标包必须要求实现基于 [Intent Atom 清单](07_intent_fidelity_and_traceability.md) 的 mutation generator，至少支持：

```text
atom deletion
polarity inversion / negation deletion
numeric boundary shift
unit substitution
comparator weakening
step reorder / dependency removal
default removal
condition or exception deletion
cancel/retry/timeout branch deletion
permission widening
source locator or hash substitution
```

每个高 criticality Atom 至少有一个语义保留正向 fixture 和一个语义破坏负向 fixture。工具无法安全生成的 mutation 必须创建人工测试 Workpack，不能直接豁免。

## 6. 正向基线测试

负向测试必须与最小正向集配对：

```text
POS-001  当前 source/atom/coverage 双向闭环
POS-002  合法 P1/C1→P2/C2→P3/C3→P4 Build Input 转换与当前 Lock 链
POS-003  Build Input→Pack→A→B0→C→Build→B1→Installability→Candidate→认证安装→D 顺序完整
POS-004  Lab challenge 与真实 Codex observation、receipt、output 完整关联
POS-005  已安装入口、import realpath 和子进程均来自认证 Artifact
POS-006  finding 正确路由、修复后重建重装并从正确门禁重入
POS-007  外部 C4 绑定全部 Hash 并签发 Certificate
POS-008  有效授权下从三工程 bootstrap 推进到硬停点，重启后保持 exactly-once 状态语义
```

正向 PASS 不能抵消任何强制负向失败。

## 7. Anti-oracle 要求

为防 Main Build 针对固定 fixture 硬编码：

- Lab 应在运行时生成 challenge、部分 mutation 参数和临时路径；
- 保留公开最小样例，但权威集合应包含未暴露的结构变体；
- 同一语义可用不同文件名、顺序无关字段和合法格式变化表达；
- checker 必须断言语义与 provenance，不得只匹配固定字符串或文件存在；
- fixture-only PASS 只能标记 `FIXTURE_COMPATIBLE`，不能声明 general runner 已验证。

## 8. 每个测试的证据包

每次测试至少输出：

```text
test_case_id + mutation_id
clean_baseline_hash
injected_delta_hash
challenge / run / scenario IDs
artifact / pack / checker / environment hashes
raw observation and receipt refs
assertion result and closed error code
finding_id + single repair_owner
invalidation set
evidence root hash
```

证据只能由 External Lab 的权威 checker 判定。Pack parser、Main Build 自测或 Linkage report 可以作为输入，但不能替代 assertion result。

## 9. C4 判定

C4 只有在以下条件同时满足时才 PASS：

1. A、B0、C、B1、D 均绑定当前 Hash 并有效；
2. P1/C1→P2/C2→P3/C3 Lock 链合法且未 stale，`P4_BUILD_INPUT_LOCK` 与 Candidate 当前有效；
3. 正向基线全部 PASS；
4. 本文强制负向/篡改矩阵全部按预期拒绝；
5. 无 open blocker、无未传播的 invalidation；
6. installed entrypoint 与 runtime root 未回退源码或执行包；
7. Lab attestation 可独立证明声明的 Codex invocation；
8. Certificate 绑定当前 Artifact、Pack、checker、baseline、环境和 evidence root。

任一条件未知时返回 `NOT_CERTIFIABLE`；不得用“未发现问题”替代证据。

## 10. 交付边界

使用本 2.8 文档包生成新目标包时，模型应把上述测试转成具体 Workpack、测试文件计划、命令、fixture、schema 和证据路径。若当轮仅生成文档，应如实标记 `PLANNED/NOT_RUN`，不能宣称负向测试、Lab、自动推进或 C4 已实现。

修复与重新认证路径见[失败回流与失效传播](10_linkage_repair_and_invalidation.md)，完整入口见 [START_HERE](../START_HERE.md)。
