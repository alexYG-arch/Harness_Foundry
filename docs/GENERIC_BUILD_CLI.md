# 通用 Build 公开宿主入口

2026-10-14 源码增量：增加全绿后的 `request-build-repair` 与可选 `ONE_ATTEMPT` 交回、
实施报告投影和 `codex_handoff`。默认连续推进不变；这些控制能力不替代外层 Codex
核实问题、判断进展和开发复验，也不证明真实模型已遵守运行约束。

2026-10-10：无需新 CLI 或审批种类。现有 compile/record 接受 Plan 1.1 增量，advance
消费同一批准；read-build 增加 phase、预算和只读观察。见[契约](FOUNDRY_UPGRADE_2026_10_10.md)。

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
| `request-build-repair` | 同上 | `program_id`, `prepared_event_id`, `targets`, `finding`；可选 `continuation_of` |
| `advance-build` | 同上 | `program_id`, `prepared_event_id`, `expected_revision`；可选 `advance_mode`, `codex_handoff` |
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
每个 attempt 另有 `implementation_commands`，从已观测实施事件返回 `event_id`、`command_id`、
`phase`、`executor`、`final_message`、`observation_root`，避免验收命令覆盖 `last_command` 后丢失
实施报告。`implementation_observation_status` 为 OBSERVED / MISSING_OBSERVATION /
NO_IMPLEMENTATION_COMMAND，并列出 `missing_implementation_command_ids`；顶层
`repair_requests` 保留返修事件依据。缺观测明确保留缺口，
`final_message` 不代表完整交接。只读取回不触发推进或命令恢复；见[报告恢复与计数](GENERIC_BUILD_RUNTIME.md#codex-报告恢复与计数交接)。
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

## 已接受产物的额外缺陷返修

外层 Codex 先核实当前版本确实违反原要求，再调用 `request-build-repair`。精确请求形状为：

```json
{
  "program_id": "current-program-id",
  "prepared_event_id": "current-prepared-event-id",
  "expected_revision": 12,
  "idempotency_key": "repair-current-finding-1",
  "targets": [{"artifact_id": "producer-output-id", "accepted_attempt_id": "current-accepted-attempt-id"}],
  "finding": {
    "requirement_refs": ["original-requirement-reference"],
    "reason": "当前版本的可达行为与原要求的具体差异",
    "evidence_refs": ["existing-counterexample-or-report-reference"],
    "repair_goal": "最小修复目标及针对性复验意图"
  }
}
```

`requirement_refs`、`evidence_refs` 是非空引用数组，`reason`、`repair_goal` 是非空文本；
`targets` 绑定当前接受的 artifact/attempt。只有同一链续修才另加 `continuation_of`，值为
原 G1 返修事件 ID。请求不接受新写域、检查器、执行器、预算或调用者自选依赖闭包。

首次请求要求该范围全部任务已接受；责任生产者必须为 CODEX。宿主检查有效批准、
原来源/检查器绑定、版本与字节身份、未决运行和完整重建预算，再原子追加
`BUILD_ACCEPTANCE_INVALIDATED`，原因是 `CODEX_CONFIRMED_REPAIR_REQUEST`。
返回 `BUILD_REPAIR_REQUESTED` 仅说明返修已登记：未执行产品命令、不新增 attempt，
`budget_reset=false`、`files_deleted=false`。原 PASS 保留，受影响当前投影为 INVALIDATED；
原生产者和依赖任务随后按原顺序实施并独立复验。原检查没有覆盖的额外缺陷还须有针对性开发复验。

同一 Program、幂等 key 和完整原请求（包括原 expected_revision）精确回放返回原事件，
即使已修复或批准后来到期也不再次失效。同 key 不同内容冲突；首次请求校验/CAS 失败不先失效。

续修绑定同一 Program/prepared 的原返修事件及当前接受版本，可在后继待重建时再次修复
尚未修好的生产者，不必先推进依赖缺陷的后继。完整待重建集合包含原影响链中尚未重建的
原生产者、当前最新失败 attempt 已被同一 Program/prepared 原生路由登记处理的消费者，
以及最新 attempt 已由原生恢复实际结算为 `NOT_DISPATCHED` 且仍关联本链既有失效事件的任务。
旧失败处理记录不覆盖新失败，未处理失败仍走原流程；缺少观测或未知副作用不推定未派发。
预算按本次失效集合与完整待重建集合的并集计入，同一任务不重复，未派发已消耗的 attempt
和实际时间不返还；旧版本已覆盖时不承诺恢复旧字节。

当前可写未接受候选、原 Plan 已声明的合法版本替换、原生独立断言修复保留原入口。
不可先改已接受字节制造漂移、伪造失败或改 SQLite；`resolve-build-attempt` 不用于全绿返修。
固定 LOCAL 责任生成器没有消费修复目标的能力时明确缺口，依赖 LOCAL 任务仍可重建。
权限、合同、预算或可用版本不足时走原变更流程，不靠新 Program 清零或继承旧批准。

## 可选单次交回与子任务交接

`advance-build` 省略 `advance_mode` 或设为 `CONTINUOUS`，保持原连续行为。
外层需在修复链每次尝试后接管判断时显式用 `ONE_ATTEMPT`：

```json
{
  "program_id": "current-program-id",
  "prepared_event_id": "current-prepared-event-id",
  "expected_revision": 13,
  "advance_mode": "ONE_ATTEMPT",
  "codex_handoff": {
    "workpack_id": "next-codex-workpack-id",
    "basis_attempt_ids": ["relevant-prior-attempt-id"],
    "summary": "已核实问题与证据；实际累计和待结算轮次；采用的原额度及剩余量；下一方法"
  }
}
```

`codex_handoff` 可省略，只可用于 ONE_ATTEMPT；只接受示例中的三个字段，摘要和 workpack ID
为非空文本，`basis_attempt_ids` 为不重复字符串数组（可以为空）。引用 attempt 属于当前
Program/prepared，接收者必须为本次实际选中的 CODEX 任务。来源可以是失败消费者，接收者
可以是原生路由选中的生产者；不要求同 workpack。归属不匹配不派发新 attempt，返回实际状态
及原因；此前依法记录的原生失效仍保留。摘要存于该 `BUILD_ATTEMPT_STARTED`，只用于该次
CODEX 实施 prompt，不复制到检查器 binding，不改变任务、权限或验收。LOCAL 不接收摘要。

一次调用只处理一个新 attempt，或结算/原生挂起一个已开始 attempt；恢复可以补同一 attempt
尚未派发的检查，不重跑已完成实施，不再开新 attempt。正在恢复时新摘要不覆盖旧上下文，
返回明确本次未用于新实施；先完成恢复取回结果，再为下一 attempt 交接，不隐式排队。
模式不跨调用继承，每次继续仍核对 revision、撤销/到期、绑定、版本和预算。

正常交回为 `BUILD_CONTROL_RETURNED`、`control_returned=true`，附原生 `attempt_status`、
attempt/workpack、revision 和预算，CLI 退出 0 只表示这次步进成功，REJECTED 仍是业务拒绝。
交回发生在当前 attempt 之后、下一轮原生修复路由或派发之前；原 HELD/STOPPED 保留非零语义。
最后 attempt 交回也不声明 Plan 完成；下一次 advance 只有经过原完成分支才返回
`PLAN_CHECKS_ACCEPTED`，如果发生漂移等变化仍按原流程处理。始终 `harness_e2e_verified=false`。

外层取回证据后，只有没有有效修改且没有新的诊断进展，才把实际开展过的修复判为无效链；
新假设被排除或获得新复现条件可继续，空 diff 本身不意味着空转。只有原生恢复实际结算为
`NOT_DISPATCHED` 才按未派发处理，不计产品失败、不判方法无效；已经使用的 attempt 和时间保留。
缺少观测或未知副作用不推断为未派发。外层按原权限、预算及中断原因决定下一次是否派发。

外层不再主动派发依赖已知未解决问题的后续工作；正常核实、修复和无关授权工作可通过已有
适用入口继续。ONE_ATTEMPT 不新增任意任务选择器，不撤销批准、不停止在跑命令，也不控制
其他调用者或连续模式。提示或报告不是机器停止协议，不能制造假合同冲突求停。

## 可选的人读状态摘要

对已有通用 Program，可只读查看中文摘要：

```bash
python3 tools/hffactory.py read-build --control-db DB --program-id ID --human
```

DB 替换为已有控制库的绝对路径，ID 替换为真实 Program ID。此命令不创建控制库、
不派发任务、不改变授权或预算。摘要显示当前计划版本、各范围状态/预算/到期时间、
历史尝试及已有恢复建议；失败详情保留原始错误码、原因和检查证据。
历史 ACCEPTED 只说明对应尝试的检查记录，不代表当前完整计划或整个 Harness 完成。

不加选项时仍输出原有缩进 JSON；`--json` 仍输出原有规范化 JSON，字段和退出码不变。
`--human` 仅支持 `read-build`，不能与 `--json` 同用；错误也用人读格式展示并保留原始返回。
摘要不是完整授权 Readback，作权限决定前仍须查看完整 JSON。普通措辞问题不新增门禁。
遵循[清晰表达规范](CLEAR_COMMUNICATION.md)，不调用额外模型润色或裁定状态。

## Scope

scope 必须完整列出以下基础字段；Plan 1.2 可另外提供下述 `verification_resources`，其他字段仍不接受：

- `workspace_root`：绝对目标目录，可尚不存在；不使用 Foundry 自身源码目录。
- `task_write_roots`：每个 Workpack 的规范相对目录数组，覆盖其声明输出。
  可尚不存在，只有批准后的 `advance-build` 才创建，绝不覆盖既有文件。
- `source_read_roots`：额外只读运行依赖目录或精确文件。已绑定 manifest 中的完整源文件、
  目标工作区及声明程序还会作为明确只读输入，须一起展示给用户。
- `verification_root`：已存在的检查器源码目录。旧 scope 要求位于实施区外；资源模式准备时复制声明文件到宿主保护区，源码可在同仓库维护，Readback 展示源码与运行副本两个位置。
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

### 可选验收资源（Plan 1.2）

2026-10-14 工作区源码已实现，未发布；源码、原生及真实业务验收证据分别记录，不能将此更新当作固定发行包已升级。旧 Plan 1.0/1.1 和没有资源引用的检查保持原有离线、零写及退出码语义；不自动迁移历史批准。

完整接入示例位于当前源码与通用包内的 `examples/resource-check/README.md`：含合成产品、受保护 unittest 检查器、Plan/scope 模板及离线/本机 HTTP 两种用法。模板不包含人工批准，不增加框架安装要求；按本页既有 review/prepare/approve/advance/read 流程接入。历史诊断包不提供这套新示例。

将 Plan 的 `schema_version` 设为 `1.2`，在需要资源的 verification 条目增加
`"resource_profile_ref": "files"`。在原完整 scope 中增加：

```json
{
  "verification_resources": {
    "schema_version": "1.0",
    "root": "/absolute/project-verification-runs",
    "checker_files": ["helper.py"],
    "profiles": {
      "files": {
        "writable_areas": ["scratch", "report-staging"],
        "network": {"mode": "NONE"},
        "services": [],
        "result_protocol": "STRUCTURED_V1",
        "required_checks": ["transaction", "migration"],
        "report_files": ["summary.json"],
        "retention": {"success": "REPORTS_ONLY", "failure_days": 7}
      }
    }
  }
}
```

这是 scope 片段，须替换实际路径与检查义务。`checker_files` 可省略；存在时列出影响判定的辅助文件，相对原 `verification_root`。准备阶段将它们及全部 `verifier://` 文件复制并绑定到宿主 `.verifiers` 目录。`checker_files` 只声明复制；检查器须通过绝对 `verifier://` 参数、`FOUNDRY_VERIFIER_ROOT` 或受保护入口的 `__file__` 实际读取判定依赖，修改产品侧源文件才不会改变本次判定。替换判定仍走原合同/范围流程。文件只读与独立进程提供普通功能验收保证，共享解释器导入被测代码不构成对抗隔离。

默认运行 cwd 仍为产品工作区，验收时产品只读。宿主为每 command 分配新的短名称目录，默认只有其 `scratch` 和 `report-staging` 叶子可写；需要项目内生成目录时可选用下述 `product_copy`。实际身份在 command 绑定中保留。资源根与产品、检查器、控制记录及声明依赖分开，不放在共享 `/tmp`。argv 独立元素可用 `resource://scratch/test.sqlite3` 或 `resource://report-staging/summary.json`；不插值 shell。实施命令尚不消费该引用，其原有合法可写区保持不变。

默认环境补入 `TMPDIR`、`TMP`、`TEMP`、`XDG_CACHE_HOME` 和 `FOUNDRY_SCRATCH_DIR`、`FOUNDRY_REPORT_DIR`、`FOUNDRY_VERIFIER_ROOT`、`FOUNDRY_PROGRAM_ID`、`FOUNDRY_PREPARED_EVENT_ID`、`FOUNDRY_ATTEMPT_ID`、`FOUNDRY_CASE_ID`、`FOUNDRY_COMMAND_ID`；子进程继承这些路径，不继承整套宿主环境或重定向 Codex HOME。仅声明下述 credentials 的检查另获对应凭据变量。SQLite 在 scratch 中正常创建库、journal/WAL/SHM；活动真实数据库必须先由其所有者生成一致性输入。

`FOUNDRY_VERIFIER_ROOT` 由宿主取自 `prepared.scope.verification_root`，指向受保护副本，并随 `resource_binding` 持久化。例如 argv 为 `['python', '-B', 'verifier://check.py', 'verifier://fixtures/expected.json']` 时，检查器中的判定与受检输入可以明确分开：

```python
expected = json.loads(Path(sys.argv[1]).read_text())  # 副本内的绝对判定参数
actual = json.loads(Path("outputs/result.json").read_text())  # 产品 cwd 内的受检输出
```

不使用参数时，把 `fixtures/expected.json` 列入 `checker_files` 并从 `Path(os.environ["FOUNDRY_VERIFIER_ROOT"], "fixtures/expected.json")` 读取；辅助模块同样按受保护位置加载。上述读取片段需在检查器中导入 json、os、sys 与 pathlib.Path，再按下述协议输出实际比较结果。裸 `Path("fixtures/expected.json")` 仍从产品 cwd 读取，当前接口不会为任意语言透明重映射，也不禁止产品 cwd 的正常输入读取。旧无资源检查不注入新环境。

必须在项目内生成缓存或构建文件时，可在该 verification 引用的 profile 增加以下可选片段；其他 profile 不需要改变：

```json
{
  "product_copy": {
    "files": ["src/tool.py", "fixtures/input.txt"],
    "writable_paths": [".cache", "build"]
  }
}
```

`files` 显式列出相对产品工作区的普通输入文件及所需依赖，包括当前未提交文件；`writable_paths` 列出副本内的生成目录。两份清单均非空、无重复且为规范相对路径，输入与生成目录不得重叠。宿主在派发前复制当时文件到本 command 的 `product`，cwd 和仅此模式提供的 `FOUNDRY_PRODUCT_ROOT` 指向该副本；副本根和输入只读，声明生成目录可写，正式产品只读。不是从 Git HEAD 导出，也不递归复制目录或跟随符号链接。此次没有 `resource://product` 引用。

输入缺失、不可读等复制准备失败会记录已分配资源及 `workload_started=false` 的设施失败，保留部分副本和实际已用 attempt；验收进程不派发、不触发产品返修。恢复已记录失败不重新复制或新增目录；尚未持久化失败记录的中断仍按既有未知窗口处理。

检查器仍经 `verifier://check.py` 的保护区绝对路径运行，判定依赖仍从 `FOUNDRY_VERIFIER_ROOT` 等保护路径读取。工具使用相对路径或 `FOUNDRY_PRODUCT_ROOT` 才会实际读取副本；工具内部绝对路径、argv 中的绝对产品路径和任意 import 搜索不会自动改写，原产品仍可读。检查器若要执行复制的 Python 工具，可使用：

```python
import os
import subprocess
import sys
from pathlib import Path

product = Path(os.environ["FOUNDRY_PRODUCT_ROOT"])
subprocess.run([sys.executable, "src/tool.py", "fixtures/input.txt"], cwd=product, check=True)
actual = (product / "build/result.txt").read_text()
```

该片段假定工具按自己的接口写入 `build/result.txt`；接入时列全所需输入，随后由受保护检查器比较独立预期并输出下述 STRUCTURED_V1 报告。片段自身不替代业务断言，生成文件不会自动作为正式附件归档。

`resource_binding.product_copy` 保存副本/来源根、文件身份清单、生成目录和实际写区；资源结果的 `product_copy_validation.status` 为 `UNCHANGED`、`CHANGED` 或 `UNAVAILABLE`。输入改变或不可核对时不依据 PASS/ASSERTION 接受或触发产品返修，原超时和未知效果保留。正常接受或产品拒绝前、恢复继续前，还按原 command 中的已声明复制清单核对当前源字节和执行位，覆盖非 artifact 的已声明依赖；不扫描未声明文件。源版本变化或不可读时沿用漂移中止，保留旧报告和副本结论；恢复原身份可继续原 attempt。正式报告和完整结果耐久后清理成功副本，失败保留；恢复沿用原 command 和已存副本核对结论，当前源版本核对不依赖副本仍存在，已清理后不重复制、不重派或再计同次 attempt。默认 cwd、网络、凭据和预算不变。此切片不提供整副本宽写、目录递归/符号链接输入，也不以副本替代真实安装位置验收。

替换 profile.network 可选择：

| 配置 | 已实现的连接范围 |
|---|---|
| `{"mode":"NONE"}` | 离线；临时文件和 SQLite 正常可写，无模型或外网探测前置 |
| `{"mode":"LOCAL_SERVICE","unix_sockets":["resource://scratch/service.sock"]}` | 该命令拥有的 Unix socket 服务；TCP/外网关闭。长路径时包装器进入 scratch 后使用相对 socket 名，业务读取仍显式使用产品路径 |
| `{"mode":"LOCAL_SERVICE","tcp":"LOOPBACK"}` | 原生授权允许 127.0.0.1、localhost、::1 的全部 TCP/UDP 端口，不是 TCP-only；外部连接除原生 53 端口例外外均拒绝；支持普通 HTTP/API 服务，不提供指定端口或本次服务隔离 |
| `{"mode":"REMOTE_SERVICE","allowed_hosts":["api.example.com"]}` | 显式启动并探测原生代理，通过支持代理的 HTTP(S) 客户端连接允许主机；拒绝其他主机和直连，不承诺端口、方法或业务操作过滤 |

`services: []` 表示本次支持由受保护检查器在一个有限命令内启动、等待就绪、调用并关闭服务；未实现跨命令后台服务管理。命令超时/撤销清理自身进程组。TCP 精确端口/服务隔离、秘密管理器与代理代持、请求级权限代理和远端写入去重/核对适配尚未实现；已有服务自身账号权限不由域名许可替代。模型服务授权与验收外联配置独立。

TCP 和 Unix socket 两种配置二选一。TCP 分支固定 loopback 主机范围，启用原生代理及 local binding；派发前分别检查 `CODEX_NETWORK_PROXY_ACTIVE=1` 和 `CODEX_NETWORK_ALLOW_LOCAL_BINDING=1`。实际策略保存 `enforcement: CODEX_NATIVE_LOOPBACK_TCP`、`loopback_protocols: ["TCP", "UDP"]`、`guarantee: LOOPBACK_ALL_PORTS_NOT_SERVICE_ISOLATION`，随 command 恢复。输入 tcp: LOOPBACK 与 enforcement 保留为兼容标识，不是 TCP-only 承诺；新增字段说明既有原生授权，不改变网络 profile 或业务检查义务，也不表示 UDP 业务验收。历史捕获不回填新字段，不因缺少字段重派或增加 attempt。外部连接保留原生 53 端口例外，该例外不检查 DNS 协议内容。该原生绑定能力也允许 `0.0.0.0` / `::`，因此检查器应显式绑定 `127.0.0.1` 或 `::1`，建议用端口 0，从服务取得实际端点并核对本次实例身份。已有指定端口也可使用，占用冲突按启动失败处理。若合同要求只有本次服务或某端口可达，当前 TCP 适配器不满足；可用 Unix socket 或后续独立网络适配。

需要测试凭据时，在该检查引用的 profile 中加入以下可选片段，不写入秘密值：

```json
{
  "credentials": {
    "API_TOKEN": {"ref": "env:FOUNDRY_TEST_API_TOKEN", "purpose": "测试服务认证"}
  }
}
```

alias 使用 `[A-Z][A-Z0-9_]*`，来源仅支持 `env:` 加 `[A-Za-z_][A-Za-z0-9_]*` 环境名，用途须非空。运行宿主用既有方式提供该环境变量，不要求用户在聊天或请求文件中粘贴 token。prepare/readback 只保存引用和用途；仅绑定的 LOCAL VERIFICATION 在通过能力探测、即将运行 workload 时解析，检查器以 `os.environ["FOUNDRY_CREDENTIAL_API_TOKEN"]` 读取。help/probes、CODEX/实施命令和未绑定此 profile 的检查不接收。缺失、空值或 NUL 返回 `workload_started=false` 的设施失败，保留实际预算，不触发产品修复。可与 NONE、本机服务和 REMOTE_SERVICE 配合，既有网络授权不变；env 名称不证明账号属性，purpose 不构成操作级权限限制。

宿主采集 stdout/stderr、预览与异常字符串时过滤已知值。summary 的原始内容仅在内存按合同判定，JSON 字符串/键（包括转义）和普通附件脱敏后归档；完成 capture 的 `credential_reports` 绑定规范判定和脱敏附件 hash/size。恢复仅核对已归档附件，不读 staging、不重新取 env 或重派；完成信封缺失或其中已绑定附件丢失/不一致时保持未知。无凭据命令的采集恢复不变。这一保证不覆盖任意 scratch、脱敏前崩溃现场或主动编码泄露；秘密管理器、代理代持和自动账号权限核实尚未实现，真实外部账号业务调用仍未验收。最新证据见源码工作区的 `docs/FOUNDRY_VERIFICATION_RESOURCES_IMPLEMENTATION_RESULT_2026_10_14.md`（本地记录不随可携带包分发）。协议仍为 2.9、Plan 1.2、资源配置 1.0，不发布。

检查器在 `FOUNDRY_REPORT_DIR/summary.json` 写入以下完整结果（身份值来自环境），成功退出 0：

```json
{
  "schema_version": "1.0",
  "case_id": "actual-case-id",
  "command_id": "actual-command-id",
  "status": "CHECKS_PASS",
  "checks": [{"id":"transaction","status":"PASS"},{"id":"migration","status":"PASS"}],
  "errors": []
}
```

`checks` 只承载已声明的合同义务，须完整且不重复；额外诊断放其他字段。真实业务失败以 `CHECKS_FAILED`、`failure_kind: ASSERTION`、对应 `FAIL` 项并退出 1；设施错误/跳过/零检查/缺报告/身份或退出码矛盾均不能通过，也不要求产品自动返工。`LOCAL_SERVICE` 另需 `services_stopped: true`；`REMOTE_SERVICE` 另需 `external_effects: NONE` 或 `CONFIRMED`，无法核实时为 `UNKNOWN` 并保留未决影响。报告是受保护检查器的观察，不是被测产品自我验收。

宿主仅复制声明的普通报告文件到正式 command 附件，拒绝符号/硬链接及特殊文件。归档临时文件使用正式 reports 外的独立宿主命名空间，完成后原子替换；summary.json.pending 等合法报告名不受限制。先持久化全部附件与结果，再清理成功暂存及选用的产品副本。普通文件清理失败记录告警，不改成产品断言失败；失败运行保留现场。`failure_days` 是保留偏好，当前无自动到期删除器。恢复使用相同 command、绑定和附件，不重派，也不把联网观测改成 DENY。

`read-build --json` 的 `resource_commands` 展示每次资源绑定、实际网络策略、报告与清理结果；`--human` 显示 cwd、资源根和能力粒度。旧案例无需为这些可选能力增加字段或审批。

### 本机 TCP 服务示例

以下是受保护检查器的最小 HTTP 资源用例。profile 选择 `{"mode":"LOCAL_SERVICE","tcp":"LOOPBACK"}`、`services: []`、`required_checks: ["http-response"]` 和 `report_files: ["summary.json"]`；其余字段沿用上例。服务绑定时分配端口，客户端以实际地址连接并用本次 command 身份确认响应，不依赖固定端口或 sleep。接入产品时替换服务和业务断言，保留独立判定依据。

```python
import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

identity = os.environ["FOUNDRY_COMMAND_ID"]

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = identity.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

server = HTTPServer(("127.0.0.1", 0), Handler)
worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
worker.start()
client = http.client.HTTPConnection(*server.server_address, timeout=2)
try:
    client.request("GET", "/")
    response = client.getresponse()
    passed = response.status == 200 and response.read().decode() == identity
finally:
    client.close()
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)

report = {
    "schema_version": "1.0",
    "case_id": os.environ["FOUNDRY_CASE_ID"],
    "command_id": identity,
    "status": "CHECKS_PASS" if passed else "CHECKS_FAILED",
    "checks": [{"id": "http-response", "status": "PASS" if passed else "FAIL"}],
    "errors": [],
    "services_stopped": not worker.is_alive(),
}
if not passed:
    report["failure_kind"] = "ASSERTION"
Path(os.environ["FOUNDRY_REPORT_DIR"], "summary.json").write_text(json.dumps(report))
raise SystemExit(0 if passed else 1)
```

请求超时或服务异常会让此示例失败并由 `finally` 关闭服务；没有完整结果不能被当作通过。其他产品服务有独立启动过程时，以有截止时间的就绪谓词替换这里的首个响应检查；同一命令预算仍涵盖启动、检查和关闭。宿主超时/撤销继续清理自己持有的进程组，不新增跨命令服务管理或重试框架。

### macOS 原生运行的目录适用性

当前接收器在共享 `/tmp`（解析后通常为 `/private/tmp`）中未能强制执行声明的只读
边界：原生离线夹具在没有写授权时仍写入成功，显式 read/deny 也没有关闭这一差异。
因此不把该目录作为可信的控制库、验证器、输入、发行运行代码或目标位置。
prepare、approve、advance 和底层命令准备会报 `SHARED_TEMP_ISOLATION_UNSUPPORTED`，
在目标派发前停止；不要用 symlink、换一个权限标签或关闭沙箱绕过。

改用普通独立工程目录，并在实际目录和同一接收器中复核只读拒绝/声明写入。
这是当前 macOS 接收器的支持限制，不是宣称已修复 Codex 的底层权限实现，
也不把一个目录的通过推广为所有宿主都通过。本地业务仍不联网，不新增授权步骤。

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

若独立检查已确定缺陷来自消费者声明的上游 ARTIFACT 输入，ASSERTION 可增加非空且去重的
`repair_artifact_ids` 数组。生产者必须当前已验收，且重建不能依赖已覆盖的历史版本。
`advance-build` 在同一范围内失效生产者及依赖后继，并在原写域/原次数内重新实施、独立检查；
不靠改名增加预算，不让 LOCAL 观察器越权编辑输入。非法归属返回 `HELD_REPAIR_SCOPE`，
已耗尽预算直接停止；不带此字段的业务拒绝保留原任务修复方式。格式错误不进入自动重试。
测试目录、二级解释器和结构化错误的适配方法见[合同对齐](ACCEPTANCE_CONTRACT_ALIGNMENT.md)。

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

退出码沿用 CLI 错误分类；`advance-build` 的 `PLAN_CHECKS_ACCEPTED`，以及显式步进的
`BUILD_CONTROL_RETURNED` 返回 0，其余推进状态仍返回 6。后者只表示控制交回，不表示业务接受。
应阅读 JSON 的 status/reason，不把进程退出 0、编译通过或自报 PASS 当业务验收。
