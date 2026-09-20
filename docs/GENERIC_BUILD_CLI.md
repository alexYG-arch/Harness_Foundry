# 通用 Build 公开宿主入口

状态：`SCOPED_M1_AND_REENTRY_ACCEPTED_NOT_RELEASE_ACCEPTANCE`。源码与本地进程回归不是
完整 PRD 接入或发行包验收。开发仓库与通用发行包的新建统一只提供本路由；旧流程已退役。
本入口只响应用户显式选择的
通用建设或有界验收案例，所有搭建路由另受下述上游文档 Review 政策约束。

入口政策已修订：所有输入先在 Foundry 上游保留问答、输出版本化搭建文档，并取得真实人工
Review，再使用本入口；原始材料保留追溯角色。后台检查全部通过也必须展示文档并等待用户确认。
见 [统一搭建文档合同](GENERIC_BUILD_PLAN.md#搭建文档与人工-review-统一入口2026-09-19)。
程序门禁已接入下列公开入口；对象合同见统一搭建文档合同。真实消息与语义映射仍由可信宿主
核对，不由 JSON 标签认证。旧 CLI 请求一律返回 `LEGACY_WORKFLOW_RETIRED`，不是可选回退；历史仍可只读。

## 一条控制链，一次范围批准

```text
上游需求问答 → 输出搭建文档 → 人工 Review → Requirement/Plan → record-build-plan → capture-build-sources
  → prepare-build-authorization → 展示 Readback → 真实后续用户批准
  → approve-build-authorization → advance-build
       → 创建批准目录 → 就绪任务 → 独立检查 → 事务验收 → 后继
                         ↑ 已知失败在预算内修复
```

人工 Review 前只准备并展示上游文档，不创建 Program 或目标。Review 后的提案/范围准备
只写显式控制库，不创建目标目录、不执行命令、不批准任务。用户批准的是
完整建设范围，不是每次内部动作；已批准范围内的调试、检查、后继推进和确定性续跑
不另设 Human Gate。需求/验收或读写/服务范围改变、撤销/到期、未知副作用仍停止。
本接口不会绕过 Codex 或操作系统权限；无原生沙箱能力时不直跑降级。

## 调用

全部命令通过 `python3 tools/hffactory.py COMMAND --json` 使用。下面的 FILE/DB
为调用者提供的具体值，不是默认路径；`--control-db` 必须为绝对文件路径。

| COMMAND | 额外参数 | request 的业务字段 |
|---|---|---|
| `record-build-plan` | `--control-db DB --request FILE` | `requirement_ir`, `plan`, `document_review` |
| `capture-build-sources` | 同上 | `program_id`, `proposal_event_id`, `source_root`, `manifest` |
| `prepare-build-authorization` | 同上 | `program_id`, `proposal_event_id`, `source_event_id`, `scope` |
| `approve-build-authorization` | 同上 | `program_id`, `prepared_event_id`, `decision` |
| `revoke-build-authorization` | 同上 | `program_id`, `prepared_event_id`, `decision`, `reason` |
| `resolve-build-attempt` | 同上 | `program_id`, `prepared_event_id`, `attempt_id`, `decision`, `reason` |
| `advance-build` | 同上 | `program_id`, `prepared_event_id`, `expected_revision` |
| `read-build` | `--control-db DB --program-id ID` | 无 request 文件 |
| `read-history` | `--database DB --program-id ID` | 只读旧 authoring 数据库，无 request 文件 |

`read-history` 只读取明确指定数据库中的原始 Program snapshot，不调用旧服务、不初始化
数据库、不重放或迁移，不把历史批准作为当前权限。主库存在非空 WAL 时拒绝读取，要求
数据库所有者先正常关闭；此入口不会代为 checkpoint。历史控制事件库不作自动格式转换；
通用 `REVISION_V1` 数据仍用 `read-build`。记录中的旧 Hash 只是原数据，不重新计算或签发。

除 `advance-build` 外的变更 request 还必须包含 `expected_revision` 和
`idempotency_key`。新控制流从 stream revision 0、Requirement/Plan revision 1
开始；后续使用命令返回的 revision。同一原始请求重试返回同一事件，不重派命令。
`advance-build` 先检查预期 revision；控制器继续逐派发与提交核对当前状态。

`read-build` 不创建缺失控制库、不写 SQLite。它给出完整 Requirement、编译 Plan、
来源信息、文档确认摘要、各准备范围及状态、任务进度、最后命令的原始结果与下一动作；来源正文不在 Readback 中重复打印。
Review 摘要标明只读历史未重新检查文件，不将历史确认当成当前可执行判定。
在途/未知尝试还提供宿主附件诊断；PID 存在不证明仍是原进程，PID 消失不证明没有副作用。
`prepare` 的 Readback 绑定该次完整 Requirement/Plan、明确源文件读取、验收文件、
范围及到期时间。提案版本、UUID 和文字状态均不是批准凭证。

各 Case 必须绑定公开的 `acceptance_contract`。prepare 在现有来源快照中解析实际行，
将 `acceptance_contracts` 投影到范围 Readback 和任务上下文；缺失或无效定位不能进入新运行。
这只是公开依据的可用性检查，不代替语义审查和正常/错误样例预检。
见[验收合同对齐](ACCEPTANCE_CONTRACT_ALIGNMENT.md)。旧范围缺少预检时只读保留，不自动追认。

Requirement/Plan 见 [Plan 合同](GENERIC_BUILD_PLAN.md)，manifest 见
[来源合同](GENERIC_SOURCE_INTAKE.md)。控制库必须使用 `REVISION_V1`；旧
`LEGACY_HASH_V1` 数据库在只读探测时拒绝，不自动迁移或继承旧授权。

## Scope

scope 必须完整列出以下字段，不接受额外字段：

- `workspace_root`：绝对目标目录，可尚不存在；不使用 Foundry 自身源码目录。
- `task_write_roots`：每个 Workpack 的规范相对目录数组，覆盖其声明输出。
  可尚不存在，只有批准后的 `advance-build` 才创建，绝不覆盖既有文件。
- `source_read_roots`：额外只读运行依赖目录或精确文件。已绑定 manifest 中的完整源文件、
  目标工作区及声明程序还会作为明确只读输入，须一起展示给用户。
- `verification_root`：已存在、位于实施工作区外的独立验证代码目录。
- `executables`：逻辑程序名到绝对程序文件的映射；LOCAL 与检查的 argv 首项引用它。
- `codex_executable`：原生 Codex receiver 的绝对程序路径。
- `model`, `allow_model_service`：CODEX 任务必须显式绑定模型并允许模型服务；
  不自动换模型或要求另配 API key。纯 LOCAL 可不授予模型服务。
- `max_attempts`, `max_task_attempts`：本范围总计及每任务的有限尝试预算。
- `command_timeout_seconds`：每个有限命令的超时（不超过一天，也不越过到期时间）。
- `expires_at`：带时区的 ISO 时间。

LOCAL/独立验证命令的后续 argv 元素可以显式使用 `executable://NAME`，例如
`["python", "-B", "verifier://check.py", "--python-executable", "executable://python"]`。
它只替换为同一 scope.executables 已声明的原始路径，未知 NAME 在准备/派发前拒绝；
不搜索 PATH、不从 `sys.executable` 推断、不改写 venv、不增加读写范围，也不做 shell 插值。
接收子程序须实际使用该参数启动子进程；只修顶层 argv 不证明整条进程链已正确绑定。

控制库、验证代码、源文档、执行器不能被目标任务写入。内部逻辑与调试由 Codex
自行选择；不规定行业阶段或算法。未开始任务可在同一 Job、执行器和完全相同的写域中
拆分/合并，也可重排互不依赖任务；完整输出集合、路径/版本链、全部 Case 命令及产物绑定、
原依赖顺序保持不变，不扩大输入。拆分沿用原任务共享预算，合并向每个原任务计费，不能靠
改名增加次数。已开始任务保留身份/结构，未验收任务仍可调整 goal/local_argv；已验收任务
不得静默改计划。公开 Plan revision 记录实施变化，不生成新批准。
已验收的声明输出变化时，控制器失效其生产任务及
依赖后继，在原范围/预算内重新建设和独立验收，不重跑无关分支、不删除文件或重置预算。
需求/来源或验证器变化仍停止；涉及已经覆盖的历史 artifact 版本时需要明确重建计划，不能虚构旧字节。

CODEX 范围准备结果包含 `coding_instruction_preflight`：列出当前默认指令发现链
需要读取的文件及未覆盖路径；只诊断，不自动增加读取范围。运行前再次核对。
如果仅需某个 `AGENTS.md`，声明精确文件，不为此开放整个仓库或客户端目录。
客户端目录仅允许显式只读的 `AGENTS.md` / `AGENTS.override.md` 文件，仍禁止
认证/状态文件、目录级读取和任何写入；不禁用指令、重定向客户端 home 或绕过沙箱。
该预检和本地 `/usr/bin/true` 沙箱探测都不证明真实 Codex 会话已经可用。

范围准备的工程验收还应在相同原生权限下运行独立检查器的离线合成样例：包括二级进程、
实际导入的扩展/动态库、零写检查以及场景写域；先确认正常样例能运行、错误样例仍被拒绝。
这不是授权前运行真实任务或模型；未获准的工具/依赖不能自动补入范围。缺依赖属于明确的
准备缺口，展示依赖差异后才能取得相应范围批准。普通环境单测和沙箱 true 探测不替代此项。

## 宿主批准与撤销

decision 的精确形状：

```json
{
  "action": "APPROVE_BUILD",
  "actor": {
    "type": "HUMAN_VIA_CODEX_CHAT",
    "chat_thread_id": "actual-host-thread-reference",
    "turn_id": "actual-later-human-message-reference"
  },
  "user_message": "真实用户批准消息原文"
}
```

示例只是格式，不是授权。撤销使用 `REVOKE_BUILD` 并另附非空 reason。
可信聊天宿主必须核实消息来自真实用户，且批准了刚展示的 prepared event 范围。
JSON 格式或 actor 字符串不能认证人；模型文本、源文档和任务进程不能自我批准。
不得虚构消息 ID、借旧案例的批准或把“准备案例”解释为模型/写域授权。
不要求人手复制 Hash 或随机冻结令牌，普通明确的自然语言批准即可由宿主记录。

撤销阻止后续派发和成功验收；活宿主的通用采集器也会检查撤销/到期并终止自己持有的
当前进程组，保留取消和部分效果观测。它不回滚既有效果、不承诺即时终止，宿主退出后
不会仅凭旧 PID 取消未知进程。具体边界见 [运行控制](GENERIC_BUILD_RUNTIME.md)。
运行过程保留实际观测；有耐久完成记录时核对后恢复，部分检查只续跑尚未派发的 Case，
不重复已完成实施。已有命令意图却没有完整观测的结果保持 HELD，不盲目重放。
若仅预留 attempt、还没有命令意图，则以控制 revision 仲裁为 `NOT_DISPATCHED`，
可以在当前授权与剩余预算内推进；旧预留仍计费，迟到调度器不能覆盖结果或重复执行。
完整观测已证明实施结束但缺声明产物时，按正常业务失败进入范围内修复，而非永久停滞。

启动/权限/接收器失败与产物检查失败分开处理：前者记录 `BLOCKED`，推进返回
`HELD_COMMAND_FAILURE`，不会自动修复或重复派发，也不会启动后继。旧事件中误标为
`REJECTED` 的同类进程失败，在仍是该任务最新结果时亦按观测停止，不改历史记录，
不推翻旧控制器后来已经完成的有效验收。只有实际缺产物或可解释的
实现/业务检查失败才进入预算内修复；未知过程保持 `HELD_UNRESOLVED_ATTEMPT`。
故障恢复不自动重置尝试数。扩大范围或追加预算仍需展示实际变化并取得后续批准，
不是每个内部 Workpack 都再次批准。

独立检查正常退出 0 仍按实际执行验收。要让非零结果驱动业务自动修复，检查器须
退出 1 并在 stdout 输出完整 JSON，例如
`{"status":"CHECKS_FAILED","failure_kind":"ASSERTION","reason":"实际值不符合要求"}`。
不能捕获全部异常后统称 ASSERTION；检查器崩溃、缺依赖、非结构化失败或被截断的
判定记为验证基础设施/未分类失败，不指使模型重写业务。既有已绑定检查器不得在运行中偷偷改写。

若缺少明确公开约定或合同/检查器矛盾，检查器退出 1 并报告 `failure_kind="CONTRACT_GAP"`。
控制器返回 `HELD_ACCEPTANCE_CONTRACT`，下一步为对齐合同及验证器，而非消耗更多实施重试。
原尝试不退款、不变成验收通过；修订源文件/检查器后仍须新范围批准。单纯参数存在不能自动
发现任意语义缺口，检查器编写者和宿主须据实际证据正确分类。

### 旧未知结果的真实处置

`resolve-build-attempt` 仅供宿主记录真实用户对具体未决效果的处置，decision.action
为 `RESOLVE_BUILD_ATTEMPT`，actor/user_message 形状同上，reason 说明核对事实与决定。
它要求已观测到进程退出或明确未启动，且该任务没有更新尝试、没有未观测命令。
无法确认进程结果时仍先核对；不能靠这个入口声明“其实没执行”。

结果为 `BUILD_ATTEMPT_RESOLVED_NOT_EXECUTED`；派生状态 `RETRY_ALLOWED` 不改历史
UNKNOWN/失败事件、不验收旧输出、不退还预算、不创建新批准或执行目标。
下一次 advance 仍检查有效范围、剩余预算和全部独立 Case。
同一目标的新 scope 不能绕过旧 scope 的 IN_FLIGHT/UNKNOWN。
正常耐久观测恢复不需要使用此入口；它不是新增的逐 Workpack 人工门。

## 大文档与证据

完整源文本进入同一控制库，派发时重新比对全文。模型收到完整只读文件的路径、
行数与 metadata，不在每次 prompt 中重复 2 MB PRD，也不截断/摘要替代原文。
`loaded_completely` 仅证明字节读取；语义遗漏、隐含依赖与未声明附件仍须审查。
源文档的命令/治理文字只作为任务数据，不是宿主指令。

`PLAN_CHECKS_ACCEPTED` 仅证明当前计划声明的独立检查和输出身份已通过并提交。
CLI 始终返回 `harness_e2e_verified=false`；真实模型、安装后使用、全 PRD 和
他人洁净接入需各自的验收材料。本入口不新增事件/消息/回执 Hash 链；仅保留
指定验证器与产物身份的基本 H2 检查。

宿主私有命令附件位于控制库旁、目标写域外，不进入发行包。双流持续排空，机器
JSONL 从原始字节增量读取，与每流 64 KiB 人读摘要分离。默认单事件上限 8 MiB、
命令双流总量上限 128 MiB；真实超限/持久化失败保持未知，展示裁剪本身不否定完整终态。

退出码沿用 CLI 错误分类；`advance-build` 未到 `PLAN_CHECKS_ACCEPTED` 返回 6。
应阅读 JSON 的 status/reason，不把进程退出 0、编译通过或自报 PASS 当业务验收。
