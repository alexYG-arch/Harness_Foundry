# 05｜Workpack 与执行模式

## 1. 核心规则

一次 Coding 执行只能激活一个 Workpack。Program 可以规划 Workpack DAG，但任何时刻 `active_workpack_id` 必须为零个或一个；并行 Agent 不得共享同一个 Candidate Workspace，也不得用“并行提速”绕过单 Workpack 边界。

阶段前驱与推进规则见[阶段状态机](./04_phase_state_machine.md)，角色权限见[Agent 与 Runtime 权责](./06_agent_and_runtime_ownership.md)，验收底线见[验收与负向测试](./11_acceptance_and_negative_tests.md)。

## 2. Workpack 的最小语义

每个 Workpack 必须只有一个可验证意图，并声明：

- `workpack_id`、Program、Phase、Profile Lock、Charter Hash；
- 唯一 `primary_layer_type`；
- `intent_text` 与不可丢失的 `intent_atom_ids`；
- 前驱 Workpack/Phase Lock；
- 锁定输入及 Hash；
- Allowed Read/Write Paths；
- Expected Outputs；
- Review Mode 与 Execution Mode；
- 结构化 Command Manifest；
- Acceptance、Quality Gap Scan、Finding 与 Return Path；
- 环境副作用边界和清理责任。

允许的 `primary_layer_type`：

```text
RULE_DEFINITION
MODULE_IMPLEMENTATION
RUNTIME_ORCHESTRATION
RELEASE_PACKAGING
TARGET_APPLICATION
CONFORMANCE_INTERFACE
CONFORMANCE_PACK
CONFORMANCE_LAB_MODULE
CONFORMANCE_LINKAGE_REVIEW
CONFORMANCE_REPAIR_ROUTING
```

一个 Workpack 不得同时承担“定义规则 + 实现所有模块 + 构建 + 安装 + 发布”。若输出跨越主要层级，必须拆分，并通过显式依赖串联。

## 3. 激活前置条件

Build Program Driver 只能在以下条件全部满足后激活 Workpack：

1. 当前没有其他 Active Workpack；
2. Phase 的 predecessor lock 与 Checkpoint 有效；
3. Workpack 的 Profile、Charter 和输入 Hash 与当前状态一致；
4. 写入路径与其他候选区不冲突；
5. Execution Mode 与 Authorization Ref 有效；
6. Command Manifest 可机械解析且无裸命令字符串；
7. 上次失败留下的 Return Path 已闭合或明确阻断。

激活、完成、失败和释放必须写入 append-only Transition/Command Ledger。不得只靠聊天消息宣告“开始下一个任务”。

## 4. 执行模式

| Execution Mode | 用途 | 可执行范围 |
| --- | --- | --- |
| `AUTHORING_ONLY` | 编写 Charter、Phase Plan、Workpack、脚本和命令声明 | 仅 Authoring Validator allowlist |
| `REGISTRATION_ONLY` | 将已批准 Program 注册到目标工程 | 仅 Manifest/Hash/路径/依赖静态校验 |
| `WORKPACK_EXECUTION` | 实现当前 Workpack | 当前 Manifest 中获批命令 |
| `PACKAGE_BUILD` | 构建不可变 Release Artifact | 构建专用命令与隔离环境 |
| `P4_INSTALLABILITY` | 在 P4 临时环境验证安装性 | Certification Installer 授权命令 |
| `CERTIFICATION_INSTALL` | 在唯一认证环境安装 Candidate | 仅一次、非 editable 安装 |
| `LAB_CERTIFICATION` | 执行独立正/负/篡改校验 | Lab Plan 授权命令 |
| `LINKAGE_READ_ONLY` | 检查声明、证据和运行映射 | 只读命令 |
| `REAL_TARGET_INSTALL` | 向真实目标应用已认证 Release | 显式 Install Authorization |

Execution Mode 不能被命令内容隐式提升。需要切换模式时，必须结束当前 Workpack，并创建独立 Workpack 和 Ledger 事件；当前 `EXECUTION_AUTHORIZATION` 必须显式列出新模式，否则停止并请求新的授权。同一授权可预先覆盖多个模式，但不能使用通配符或包含 `REAL_TARGET_INSTALL`。

## 5. Authoring 与 Registration 永不执行未来任务

`AUTHORING_ONLY` 和 `REGISTRATION_ONLY` 均为非执行态：

- 不执行刚生成的 Workpack、脚本、Runbook、示例或 Program Driver 配置；
- 不构建包、不安装 Harness、不启动服务、不运行迁移；
- 不调用最终 Harness Runtime；
- 不因文档中出现 `run`、`install`、`test` 等文本而获得执行权限；
- Registration 只验证并登记，不等于安装、启动或激活第一个 Workpack。

Authoring Validator 可以检查 JSON/Schema、引用、Hash、路径安全和命令结构，但其 Command ID 必须预先位于 Authoring allowlist。生成物中的所有命令默认 `DECLARE_ONLY`。

## 6. 结构化 Command Manifest

禁止把原始 shell 字符串作为权威命令。每条命令至少包含：

```json
{
  "command_id": "P2-WP-003-ACCEPT-01",
  "classification": "ACCEPTANCE",
  "execution_mode": "WORKPACK_EXECUTION",
  "executable": "/absolute/path/to/python",
  "argv": ["-m", "pytest", "tests/vertical_slice", "-q"],
  "working_directory": "/absolute/candidate/workspace",
  "environment_allowlist": {
    "PYTHONHASHSEED": "0"
  },
  "forbidden_environment_keys": ["PYTHONPATH"],
  "target_environment_id": "candidate-P2-WP-003",
  "authorization_ref": "AUTH-...",
  "timeout_seconds": 600,
  "expected_exit_codes": [0],
  "side_effect_boundary": ["candidate_workspace"],
  "stdout_artifact": "evidence/.../stdout.log",
  "stderr_artifact": "evidence/.../stderr.log"
}
```

机械规则：

1. `argv` 必须是 token 数组，不得是单字符串。
2. 禁止 `shell=true`、`eval`、命令替换、管道、重定向和 `&&`/`;` 串联；不得用 `/bin/sh -c`、`bash -c`、`zsh -c`、PowerShell command string 等重新包回裸命令。
3. 可执行文件和工作目录必须先 realpath，再检查允许边界。
4. 不得通过 PATH 解析不确定的同名程序；认证与安装命令必须使用绝对入口。
5. 环境变量采用 allowlist；敏感值只记录名称和安全摘要，不写入日志。
6. 运行前再次比对 Workpack、Mode、Target Env 和 Authorization。
7. 运行后记录实际 executable realpath/hash、argv、cwd、环境摘要、开始/结束时间、exit code 与输出 Hash。

文档中的命令示例仅用于说明，不构成可执行授权。

## 7. 单 Workpack 执行协议

```text
Preflight
-> lock inputs and scope
-> activate exactly one Workpack
-> hydrate isolated Capsule
-> execute allowlisted implementation commands
-> bounded review/fix when authorized
-> run acceptance commands
-> quality gap scan
-> postflight validator
-> write Workpack Result
-> promotion or return path
-> release active_workpack_id
```

只有 Workpack Result 为 PASS 且 Candidate 被显式 Promotion 后，其输出才进入阶段聚合。Promotion 可以由具备明确授权的 Driver 执行，但必须生成独立 Ledger 事件；不得仅因 PASS 隐式发生。`LOOP_CONVERGED`、测试退出码 0、文件存在或 Coding Agent 自述完成均不等于 PASS。

## 8. Review/Fix 边界

R/F Loop 是可选强化，不是默认批准器：

- Reviewer 只读；Fixer 只修复已登记、OPEN、在当前 intent 与写入范围内的 Finding；
- 不得修改 Charter、Profile、前驱 Lock、Acceptance 或权威 Spec；
- 不得 Promotion、Seal、Lock、Commit、安装或激活下一 Workpack；
- 发现跨层、跨 Phase 或缺失 Outcome 时必须创建 Return Path；
- 最大轮数、振荡检测和停止条件必须预先声明。

## 9. Workpack PASS 的必要证据

Workpack Result 至少绑定：

- Canonical Intent Atom 覆盖结果；
- 所有实际写入路径与 Diff Hash；
- 完整 Command Ledger；
- Acceptance 与 Postflight Report；
- Quality Gap Scan 与 Finding Closure；
- 环境副作用与清理 Receipt；
- 未执行任何未授权/声明态命令的证明；
- 未改变 Profile、Charter 和 predecessor lock 的证明。

PASS 只证明当前 Workpack。Phase Gate 还必须验证 Workpack 并集覆盖 Outcome、运行路径和系统级责任，防止一组局部 PASS 漏掉最终 Orchestrator。

## 10. 失败、修复与重新执行

失败时不得在 Lab、Linkage 或安装环境中临时 Patch。必须：

1. 输出结构化 Finding 与 owner Phase/Workpack；
2. 失效受影响的 Candidate、阶段 Lock 及下游资产；
3. 创建新的 Repair Workpack；
4. 在独立 Candidate Workspace 修复；
5. 重新执行 Acceptance、Promotion、Phase Gate；
6. 如制品或认证链受影响，按[构建、发布与安装](./09_build_release_install.md)重新构建、安装和认证。

任何“继续下一阶段并稍后补 P3”“先让 P4 通过再回填证据”的行为都必须由 Driver 拒绝。

## 11. 授权范围内的连续推进

Authoring 和 Registration 继续保持 `auto_start=false`。完成批准与注册后，Driver 可在有效 `EXECUTION_AUTHORIZATION` 内重复：

```text
select exactly one next action
→ acquire lease
→ preflight authorization and hashes
→ execute one Workpack/Gate
→ validate and atomically commit result
→ release lease
→ reevaluate policy and hard stops
```

连续推进不是“自动通过”。每轮必须重新读取状态、授权、Lock、Finding 和 loop budget。模式超出授权、需要 Human Gate、P3 N/A、发生振荡、权限扩大或下一动作不唯一时立即停止。完整契约见[Program Driver、Loop 与恢复](./15_program_driver_loop_and_recovery.md)。
