# 06｜Agent、Runner 与 Runtime 权责

## 1. 原则

角色分离用于建立可信边界，不是换名称。生成实现、执行命令、见证 LLM/Codex 调用、校验结果、安装制品和签发证书必须由明确 Owner 承担；任何角色不得用自己生成的 self-reported receipt 证明自己真实执行过某项能力。

执行模式见[Workpack 与执行模式](./05_workpack_and_execution_modes.md)，独立认证边界见[Conformance 架构](./08_conformance_architecture.md)，安装环境见[构建、发布与安装](./09_build_release_install.md)。

## 2. 角色清单

| 角色 | 主要责任 | 明确禁止 |
| --- | --- | --- |
| Program Author | 生成 Charter Start 执行包与计划 | 执行未来 Workpack、安装 Harness |
| Build Program Driver | 校验三工程/阶段/发布状态并激活唯一下一动作 | 承担最终 Harness 业务运行、越过授权或替代 Gate Owner |
| Coding Agent | 在当前 Workpack 范围实现 Candidate | 改 Lock、越权安装、自行认证 |
| Reviewer/Fixer | 有界发现和修复 Finding | Promotion、推进 Phase、扩展 intent |
| Final Harness Runtime | 运行安装后的最终 Harness | 读取/激活 Build Workpack、返回执行包 |
| Trusted Runner | 按授权启动 Codex/LLM/命令并记录可信见证 | 决定业务 PASS、补写模型自述字段 |
| Foundry Conformance Lab | 独立执行校验并签发 Certificate/Findings | 修改 Harness、修复 Candidate、代替安装 Owner |
| Linkage Review | 只读检查协议—Pack—制品—运行映射 | 安装、执行修复、签发最终证书 |
| Certification Installer | 唯一负责环境创建和安装变更 | 修改源码、判断 Conformance PASS |
| Human Gate Owner | 批准 Charter、例外、N/A 和真实安装 | 用口头批准替代结构化证据 |

## 3. Build Program Driver 与 Final Harness Runtime 必须分离

两者必须是不同的入口、命令身份、配置域和输出根：

| 项目 | Build Program Driver | Final Harness Runtime |
| --- | --- | --- |
| 目的 | 建设 Harness | 使用 Harness 处理真实输入 |
| 输入 | Charter、Phase、Workpack、Lock | 用户输入、目标配置、运行请求 |
| 入口 | build-program 专用绝对入口 | 安装分发包提供的绝对入口 |
| 输出 | Candidate、Evidence、Lock、Ledger | Harness 业务结果、Runtime Trace |
| 工作目录 | Build Project/Candidate Workspace | 源码和执行包之外的 Runtime Workspace |
| 禁止读取 | 真实运行秘密（除显式 fixture） | Workpack 激活队列、Authoring Capsule |

强制检查：

- 最终运行的进程根必须是 Final Harness Runtime，而不是 Program Driver 或某个 Phase 脚本；
- Final Runtime 不得导入 Build Program Driver 包、回到 Start Package 目录或调用 Workpack Dispatcher；
- Driver 不得伪装成最终 CLI 返回“运行成功”；
- Runtime Trace 必须记录入口 realpath/hash、distribution、版本、父进程与安装来源；
- 检测到执行包入口、repo script、PATH shadow 或 source import 时返回 `FINAL_RUNTIME_ORIGIN_MISMATCH`。

## 4. 三类证据不得混为一体

1. **Harness Runtime Receipt**：Harness 声明它处理了什么输入、产生什么输出。
2. **Trusted Runner Attestation**：独立 Runner 见证实际启动了哪个 executable/endpoint、Codex/LLM session 和进程。
3. **Lab Verdict / C4 Report**：Lab 根据规范、Attestation、Receipt、Trace 和负向测试给出 Installed Certification PASS/FAIL。

Runtime Receipt 的 Hash 只能证明内容在记录后未改变，不能证明内容来自 Codex、LLM 或指定 Runtime。Lab 不得将 `executor_type="codex"`、非空 `session_ref` 或一组自洽 Hash 当作真实调用证明。

## 5. Codex/LLM 可信 Attestation 协议

凡 Charter 要求 Codex/LLM 执行的 Stage，必须由 Lab 与 Trusted Runner 建立挑战—见证链：

```text
Lab issues one-time challenge nonce
-> Runner validates authorized StageSpec and command
-> Runner launches the approved Codex/LLM boundary
-> Runner records invocation start/end and raw trace hash
-> Harness writes Runtime Receipt bound to the same nonce
-> Lab cross-checks Attestation, Receipt, output and trace
```

Runner Attestation 至少包含：

- 一次性 `challenge_nonce`、run/stage/program/release/environment ID；
- Runner 身份、版本、签名/完整性机制和可信时间；
- 实际 executable/adapter 的 realpath、Hash、版本和分发来源；
- 不泄露秘密的 endpoint/provider/model 身份摘要；
- provider request/session ID 或 Codex session ID（若接口提供）；
- argv 或 request envelope Hash、prompt/input Hash、output Hash；
- PID/父进程、开始结束事件、exit/status、超时与取消状态；
- raw invocation trace 的内容 Hash 与只读存储引用；
- 与 Harness Runtime Receipt 的双向绑定 Hash。

Challenge 必须一次性使用并设有效期。重复 nonce、跨 Stage/Release 重放、输出替换、Runner 身份未知、trace 缺失或只存在 Harness 自报 receipt 时，结果必须为 `INVOCATION_UNVERIFIED`，不能降级为警告。

## 6. Trusted Runner 的边界

Trusted Runner 只证明“实际调用发生及其可核对属性”，不证明输出质量。它必须：

- 从结构化 Command/Invocation Manifest 运行，不解释 Markdown 命令；
- 校验 Execution Mode、Authorization、Stage owner 和环境；
- 不允许 Harness 进程自行提交等价的 Runner Attestation；
- 保存最小必要追踪信息并对敏感内容脱敏；
- 将调用失败、未调用、fallback 到纯 Python、本地 stub 或 mock 明确区分。

若 Stage 允许确定性 Python 实现，Charter 必须显式声明；它不能冒充要求 Codex/LLM 的 Stage。若发生 fallback，Receipt 与 Attestation 均须写明 `actual_executor`，Lab 按 StageSpec 决定 FAIL，而不是依据输出是否看似正确。

## 7. Lab 与 Linkage 的独立性

Foundry Conformance Lab 拥有权威 Checker 实现和 Certificate 判定；Linkage Review 只检查：

- Charter Outcome 到 Workpack/Stage/Run Path/Scenario/Checker 的连接；
- Protocol/Schema/Pack/Artifact/Installed Runtime 的绑定；
- Finding 到 owner Phase、Repair Workpack 和重认证路径。

Linkage 不能复制一套权威 Checker 并给出第二个 PASS；Lab 也不能在 Candidate 中修代码。二者发现问题时只输出结构化 Finding，修复必须回到 Main Harness Build Project。

## 8. Agent 交接契约

每次 Agent 交接必须写出：

- 当前 Program、Profile、Phase、Workpack 与锁定输入；
- `highest_touched_phase`、`highest_locally_closed_phase`；
- 已执行 Command ID 与 Ledger 引用；
- Candidate Diff、证据、开放 Finding 和 Return Path；
- 未执行的声明态命令；
- 下一角色可做与禁止做的动作。

聊天摘要不能替代交接资产。接手 Agent 必须重新验证 Hash 和状态机，不得因前一 Agent 声称“已完成 P3”而直接进入 P4。

## 9. 权限冲突处理

当同一进程或身份同时承担互斥角色时，必须拒绝本次权威动作：

- Coding Agent 不能签发自己的 Lab Verdict；
- Lab 不能安装或修复被测 Harness；
- Linkage 不能修改 Pack 以让绑定通过；
- Final Runtime 不能激活 Repair Workpack；
- Certification Installer 不能替换失败制品；
- Program Driver 不能签发 Certified Release Lock。

必要时可复用基础设施，但执行身份、权限、工作区、Ledger 和签名边界必须独立且可验证。

## 10. Driver 的跨工程协调边界

Program Driver 是控制平面角色，不是第四个校验工程。它可以读取 Main、Lab、Linkage 状态，选择机器 DAG 中唯一 ready 节点并登记 barrier；不能修改 Lab verdict、把 Linkage report 提升为证书，或让一个工程代替另一个工程完成其 owner 动作。

Driver 的每个动作必须绑定 `actor_role`、Authorization、Project ID、Mode、Command ID、lease 和 idempotency key。跨工程状态只有在各 owner 产物 Hash 被重新读取后才能提交，聊天消息或模型自述不能解除 barrier。
