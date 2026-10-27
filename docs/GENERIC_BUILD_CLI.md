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

完整信息已备齐时，可先用 `preview-build` 保存非执行预览，展示合同与完整运行范围后取得一次明确确认，再用 `materialize-build-preview` 落到同一事件流。预览不注册 Program、不创建目标、不执行模型／业务；可能创建的检查器快照仅在已列明的宿主准备区。以下原分步流程保持兼容。

```text
上游需求问答 → 输出搭建文档 → 人工 Review → Requirement/Plan → record-build-plan → capture-build-sources
  → prepare-build-authorization → 展示 Readback → 真实后续用户批准
  → approve-build-authorization → advance-build
       → 创建批准目录 → 就绪任务 → 独立检查 → 事务验收 → 后继
                         ↑ 已知失败在预算内修复
```

人工 Review 前可以准备完整非执行预览并展示合同与范围，不创建 Program 或目标。Review 后的提案/范围准备
只写显式控制库，不创建目标目录、不执行命令、不批准任务。用户批准的是
完整建设范围，不是每次内部动作；已批准范围内的调试、检查、后继推进和确定性续跑
不另设 Human Gate。需求/验收或读写/服务范围改变、撤销/到期、未知副作用仍停止。
本接口不会绕过 Codex 或操作系统权限；无原生沙箱能力时不直跑降级。

## 调用

通用入口的参数解析错误（未知命令、缺少必填参数、未知选项、互斥选项）向 stdout
输出一个 JSON 错误对象，退出码为 2；是否显式提供 `--json` 不改变该错误格式。
错误码为 `REQUEST_VALIDATION_ERROR`，`error.details.reason_code` 为 `CLI_ARGUMENT_ERROR`，
并明确 `writes_performed=false`、`execution_started=false`。解析失败不读取请求或打开控制库，
也不启动业务执行。`--help` 仍输出帮助文本并以 0 退出，正常调用与历史入口退役语义不变。
源码诊断命令不属于本次参数格式调整；通用发行包不提供 `verify-spec`、`validate-core`，
运行包的初始自检使用 `version --json` 和 `--help`。

宿主要求 Python 3.11 或以上；用已选环境的绝对解释器路径调用
`/absolute/project/.venv/bin/python -B tools/hffactory.py COMMAND --json`。
文档中的 `python3` 是满足此版本要求的解释器示意，不表示可以在运行或接续时重新搜索 PATH。
错误版本会在核心导入前报告实际解释器、版本及显式重启示例；提示不会自动启动其他解释器、
复制虚拟环境或改变权限，建议中的本项目 `.venv` 是否满足条件仍需确认。已支持的
`python -m harness_foundry_factory.build_cli` 使用同一检查；源码方式须让 `src` 在模块读取路径中。
下面的 FILE/DB 为调用者提供的具体值，不是默认路径；`--control-db` 必须为绝对文件路径。

宿主读取和接续保持同一已绑定解释器，例如保存 `HOST_PYTHON=/absolute/project/.venv/bin/python` 后，
以 `"$HOST_PYTHON" -B tools/hffactory.py read-build ...` 核对状态，再以同一
`"$HOST_PYTHON" -B tools/hffactory.py advance-build --control-db DB --request NEXT_REQUEST --json`
继续已批准范围。NEXT_REQUEST 使用当前 prepared/revision，不重建预算；LOCAL 与检查的
子进程仍沿 `scope.executables`、`executable://python` 的现有绑定，不能从宿主 `sys.executable`
或 PATH 偷换它们。启动诊断不新增业务授权，也不更改原进程恢复规则。

| COMMAND | 额外参数 | request 的业务字段 |
|---|---|---|
| `preview-build` | `--control-db DB --request FILE` | 完整非执行预览，字段见下文；无 revision/幂等 key |
| `materialize-build-preview` | 同上 | 预览引用、展示记录、明确同时确认的真实决定、初始 revision 与幂等 key |
| `derive-build-correction` | 同上 | `program_id`, `prepared_event_id`, `evidence` |
| `resolve-build-technical-attempt` | 同上 | `program_id`, `prepared_event_id`, `attempt_id`, `evidence` |
| `record-build-plan` | `--control-db DB --request FILE` | `requirement_ir`, `plan`, `document_review` |
| `capture-build-sources` | 同上 | `program_id`, `proposal_event_id`, `source_root`, `manifest` |
| `prepare-build-authorization` | 同上 | `program_id`, `proposal_event_id`, `source_event_id`, `scope`；可选 `rebind_from`, `follow_codex_defaults` |
| `approve-build-authorization` | 同上 | `program_id`, `prepared_event_id`, `decision` |
| `revoke-build-authorization` | 同上 | `program_id`, `prepared_event_id`, `decision`, `reason` |
| `reconcile-build-observations` | 同上 | `program_id`, `prepared_event_id` |
| `reassess-build-attempt` | 同上 | `program_id`, `prepared_event_id`, `attempt_id`, `decision`, `evidence` |
| `resolve-build-attempt` | 同上 | `program_id`, `prepared_event_id`, `attempt_id`, `decision`, `reason`；可选 `host_reconciliation` |
| `request-build-repair` | 同上 | `program_id`, `prepared_event_id`, `targets`, `finding`；可选 `continuation_of` |
| `advance-build` | 同上 | `program_id`, `prepared_event_id`, `expected_revision`；可选 `advance_mode`, `codex_handoff` |
| `read-build` | `--control-db DB --program-id ID` | 无 request 文件 |
| `read-history` | `--database DB --program-id ID` | 只读旧 authoring 数据库，无 request 文件 |

`read-history` 只读取明确指定数据库中的原始 Program snapshot，不调用旧服务、不初始化
数据库、不重放或迁移，不把历史批准作为当前权限。主库存在非空 WAL 时拒绝读取，要求
数据库所有者先正常关闭；此入口不会代为 checkpoint。历史控制事件库不作自动格式转换；
通用 `REVISION_V1` 数据仍用 `read-build`。记录中的旧 Hash 只是原数据，不重新计算或签发。

除 `advance-build`、非执行的 `preview-build` 外的变更 request 还必须包含 `expected_revision` 和
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

新建控制库可在 `record-build-plan` 或 `preview-build` 请求顶层显式选择
`"physical_format": "REVISION_BODIES_V1"`。这是同一 SQLite 内来源正文去重的物理格式；
逻辑事件仍为 `REVISION_V1`，协议仍为2.9。省略时，新库沿用原内联格式。
现有库自动识别其原格式；显式选择不一致会报错，不转换、清空或重建旧库。
后续捕获、准备、运行及取回沿原入口和原数据库路径，`read-build` 返回实际物理格式。

新格式把来源捕获及 preview 中的相同 UTF-8 正文保存在同库不可变正文表，
事件保留各自来源身份、路径、版本和时间。幂等记录保留完整请求语义及有序原事件引用；
取回恢复原正文和结果，不再派发或重复计数。缺失或损坏正文不能视为完整证据。
已有有效来源绑定仍按原路线复用；显式再次捕获仍生成新的来源事实，不因去重省略。

采用新格式前需保留旧工具和旧库：旧运行器拒绝这种新库，不能用它回滚写入。
备份仍应使用 SQLite 一致备份并另保全库外观察、检查器和产物；同库去重不代替这些材料。
本入口仅用于新库，旧库迁移、采用及增量回滚另行验证；升级代码不会让原库自动缩小。
它不改变授权、预算、恢复、模型或服务配置，也不要求所有项目切换格式。

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

## 宿主工具成果的后续独立检查

需要浏览器、检索或其他宿主工具的业务，按真实工作流先取回已完成任务的产物和原命令记录，再由独立宿主调用工具并固定审阅证据。ONE_ATTEMPT 在整次尝试后返回；不存在默认的“生成后、检查前暂停”接口。

后续检查继续准备普通 LOCAL 任务：只复制/读取明确的既有成果，把检查器、原始判定依据、所审成果/工作流版本和宿主证据逐文件列入 verification_resources.checker_files；argv 的 verifier:// 引用必须指向普通文件，不能用目录充当文件。保护检查器实际从副本读取依赖，以实际 FOUNDRY_CASE_ID/FOUNDRY_COMMAND_ID 写 STRUCTURED_V1 报告。不重新调用已完成生产者来填补报告。

自动准备通过与业务完成分开。缺证或版本不适用按该检查合同保留 ERROR/未验收；有独立依据的业务失败沿 ASSERTION 原生修复分类。 此类固定复制的 LOCAL 复验用 `ONE_ATTEMPT` 单次交回并读回实际状态；它不能修复业务，不能因 ASSERTION 连续重派同一复制命令。外层携带真实失败证据回原生产者，沿其既有适用返修入口、授权和预算处理；宿主产出则回原宿主流程。修复后重新审阅受影响成果、固定新证据并准备新的复验，保留旧失败与消耗；不为取证重放生产者，正常缺陷修复所需的生产步骤仍可运行。只有控制器提交才能成为正式接受，宿主 JSON 不取得接受权。跨 Program 的控制库/Program/prepared/attempt/产物/readback_revision 用普通 handoff 关联，不将旧 ID 填入本任务 basis_attempt_ids，不另建计数或批准规则。

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

scope 必须完整列出以下基础字段，`model` 可省略；可另提供 `model_reasoning_effort`，Plan 1.2 可提供下述 `verification_resources`：

- `workspace_root`：绝对目标目录，可尚不存在；不使用 Foundry 自身源码目录。
- `task_write_roots`：每个 Workpack 的规范相对目录数组，覆盖其声明输出。
  可尚不存在，只有批准后的 `advance-build` 才创建，绝不覆盖既有文件。
- `source_read_roots`：额外只读运行依赖目录或精确文件。已绑定 manifest 中的完整源文件、
  目标工作区及声明程序还会作为明确只读输入，须一起展示给用户。
- `verification_root`：已存在的检查器源码目录。旧 scope 要求位于实施区外；资源模式准备时复制声明文件到宿主保护区，源码可在同仓库维护，Readback 展示源码与运行副本两个位置。
- `executables`：逻辑程序名到绝对程序文件的映射；LOCAL 与检查的 argv 首项引用它。
- `codex_executable`：原生 Codex receiver 的绝对程序路径。
- `model`, `allow_model_service`：新 CODEX 请求未指定模型（省略或 null）、推理强度或选择策略时，
  默认跟随 Codex 全局模型和推理强度；仍须明确允许模型服务。显式模型保持固定，
  不静默替换用户选择或要求另配 API key。纯 LOCAL 不读取模型默认配置，也不要求模型服务。
- `model_reasoning_effort`：可选的明确推理强度，由已绑定 Codex/模型支持；不自行映射到另一强度。
- `max_attempts`, `max_task_attempts`：本范围总计及每任务的有限尝试预算。
- `command_timeout_seconds`：每个有限命令的超时（不超过一天，也不越过到期时间）。
- `expires_at`：带时区的 ISO 时间。

日常新请求无需手动选型：省略 `model` 或填写 null，并省略 `model_policy`、推理强度和
冻结开关，prepare 会保存明确的 `CODEX_GLOBAL_DEFAULTS` 策略及选定服务。准备仍未授权；
在原批准服务范围内，每条新命令跟随当时全局模型/强度，不增加逐次确认。
这读取全局配置，不承诺继承当前聊天临时选择。相同 prepare 请求先返回原记录，
不重新读取默认；旧 prepared、已批准固定值及完整报告恢复均不重新解释。
显式 `model` 继续按固定模型处理，可用 `model_policy: FIXED` 明示；仅指定推理强度
不代表允许忽略该值，固定选择仍须给出模型。对照测试应显式固定相同模型/强度，
或采用下述准备时冻结方式；不会将已有固定比较自动改成动态默认。

要沿用 Codex **全局默认模型与推理强度并在准备时冻结**，在 prepare request 顶层加入
`"follow_codex_defaults": true`，scope 中 `model` 为 null，且不同时填写推理强度。
准备通过声明的 Codex `app-server config/read`（无项目 cwd）取得原生有效配置，
保存具体模型、强度和选定 `model_service`，Readback 返回 `model_defaults_source`。
读取失败或缺少具体模型/强度时明确诊断，不猜测默认值。此读取没有模型 turn，
不创建目标任务；Codex 可能初始化自己的本机状态。同一 prepare 幂等键复用首次选择。
后续配置变化不改已批准 scope；改用服务或冻结值时沿原 `rebind_from` 接续并保留累计消耗。

`model_service` 是可选的公开服务绑定：`{"provider": "example", "config": {...}}`。
未提供的既有固定模型请求仍用原 OpenAI receiver，不读取全局默认；显式提供时使用该服务。
`config` 只接入所选 provider 的声明字段，例如 `name`、`base_url`、`wire_api`、
`requires_openai_auth`、`env_key`、`env_http_headers` 及重试/流参数；绝不导入用户工具权限、
MCP、hooks 或任意启动命令。具体字段以校验器诊断为准。原生认证仍由 Codex 处理；
环境凭据只保存变量引用，在实际模型派发前取值并仅交给客户端，不进入 Plan、prompt、
Readback、命令行或日志，不让模型工具继承。日志中的已知凭据回显按内容脱敏；CODEX 的 JSONL 仍保留事件类型、退出状态和使用量等协议事实，相同数字或协议词不因此被改写。阻断报告仅保留合法 `failure_kind="CONTRACT_GAP"` 枚举，其他值仍脱敏，且原无效报告不会因此变为有效。缺少凭据明确报告未启动，不自动反复派发。
本次未接入内联凭据、静态 HTTP headers/query 参数或命令式认证；这些不能被写成已经支持。
不对凭据内容附加业务格式要求，也不修改宿主环境或全局配置。

也可明确指定**每次命令跟随默认模型/强度**，使用 scope 的
`"model_policy": "CODEX_GLOBAL_DEFAULTS"`、`"model": null`，不填写推理强度，
不与 `follow_codex_defaults` 混用。准备仍读取一次原生配置并固定 `model_service`；
实际派发只重选模型/强度，服务身份、端点或认证声明变化时按原范围变更处理，
不能由 `allow_model_service: true` 推定批准了任意新服务。原生未明确的动态默认值如实保留 null，
不声称已经冻结具体选择。每条命令在启动前保存实际选择及来源，恢复只读原绑定。
旧动态 scope 没有服务绑定时仍可读取、取回报告和处置未决尝试；新派发需通过同 Program 的
`rebind_from` 补齐服务范围及真实批准，不新建预算、不改旧 prepared，也不重跑已接受任务。
已有服务绑定且仍在批准条件内的正常动态模型选择，不增加逐命令审批。

正式派发保留 `--ignore-user-config`、原授权校验、读写及网络边界。配置读取和参数记录
不等于服务端实际模型认证，更不等于业务验收；工程接收器测试和真实模型验证分别报告。

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
| `{"mode":"LOCAL_SERVICE","tcp":"LOOPBACK"}` | 原生授权允许 127.0.0.1、localhost、::1 的全部 TCP/UDP 端口，不是 TCP-only；外部连接拒绝；接收器可能保留原生 53 端口例外，但不保证许可；支持普通 HTTP/API 服务，不提供指定端口或本次服务隔离 |
| `{"mode":"REMOTE_SERVICE","allowed_hosts":["api.example.com"]}` | 显式启动并探测原生代理，通过支持代理的 HTTP(S) 客户端连接允许主机；拒绝其他主机和直连，不承诺端口、方法或业务操作过滤 |

`services: []` 表示本次支持由受保护检查器在一个有限命令内启动、等待就绪、调用并关闭服务；未实现跨命令后台服务管理。命令超时/撤销清理自身进程组。TCP 精确端口/服务隔离、秘密管理器与代理代持、请求级权限代理和远端写入去重/核对适配尚未实现；已有服务自身账号权限不由域名许可替代。模型服务授权与验收外联配置独立。

TCP 和 Unix socket 可分别选择，也可显式组合为 `{"mode":"LOCAL_SERVICE","tcp":"LOOPBACK","unix_sockets":["resource://scratch/service.sock"]}`。组合同时验证回环接收器能力及每个自有 socket，不能自动扩大旧单模式批准。TCP 分支固定 loopback 主机范围，启用原生代理及 local binding；派发前分别检查 `CODEX_NETWORK_PROXY_ACTIVE=1` 和 `CODEX_NETWORK_ALLOW_LOCAL_BINDING=1`。实际策略保存 `enforcement: CODEX_NATIVE_LOOPBACK_TCP`、`loopback_protocols: ["TCP", "UDP"]`、`guarantee: LOOPBACK_ALL_PORTS_NOT_SERVICE_ISOLATION`，随 command 恢复。输入 tcp: LOOPBACK 与 enforcement 保留为兼容标识，不是 TCP-only 承诺；新增字段说明既有原生授权，不改变网络 profile 或业务检查义务，也不表示 UDP 业务验收。历史捕获不回填新字段，不因缺少字段重派或增加 attempt。接收器可能保留原生 53 端口例外，也可能更严格地拒绝；这是权限上限，不保证 DNS 可用，该例外不检查 DNS 协议内容。该原生绑定能力也允许 `0.0.0.0` / `::`，因此检查器应显式绑定 `127.0.0.1` 或 `::1`，建议用端口 0，从服务取得实际端点并核对本次实例身份。已有指定端口也可使用，占用冲突按启动失败处理。若合同要求只有本次服务或某端口可达，当前 TCP 适配器不满足；可用 Unix socket 或后续独立网络适配。

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
无预检的 effects 基线准备失败，在完整原生事件证明尚无命令意图时，结清为
`NOT_DISPATCHED` 并交回原诊断；旧 UNKNOWN 追加恢复结果，保留原异常和预算。
本次 advance 不因同一准备错误连续派发；配置修正后的正常推进仍可继续。
残缺、矛盾或存在未决命令的记录不适用无命令恢复。

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
它要求该任务没有更新尝试，且每条已观测命令已有退出/明确未启动事实。
仍为 IN_FLIGHT 但退出结果已完整取回的尝试也可处置；这不证明旧产物已验收。

先用 `reconcile-build-observations` 取回原命令附件。该入口只追加已有完整结果及取回摘要，
不启动业务/检查器、不接受产物、不加 attempt、不清理资源，可在原授权过期或撤销后使用。
无完整结果就保持缺失；资源检查只取已完成归档与清理的收据，尚需资源收尾的留待有效授权处理。
取回后的继续执行仍走原 `advance-build` 授权校验，不能借取回恢复权限。

原退出附件永久缺失时，可信宿主可在真实用户处置之外提供 `host_reconciliation`：
`prepared_event_id`、`attempt_id`，以及恰好覆盖所有未观测命令的 `commands` 数组。
每项包含原 `command_id`、`executor`、`observation_root`；`termination` 包含
`status`（`PROCESS_TREE_TERMINATED` 或 `NOT_STARTED`）、`detail`、非空 `evidence_refs`；
`effects` 包含 `status: RECONCILED_FOR_RETRY`、`detail`、非空 `evidence_refs`。
有 STARTED 事实的命令不能申报 NOT_STARTED。宿主须实际核实整个命令进程树停止，以及
既有效果如何保留/处置；引用可以指向宿主观察和接收端核对记录。接口校验身份与完整性，
无法凭 JSON 认证这些事实，必须由可信宿主负责，不能由产品模型自报。
它保留原缺失观察和宿主处置记录，不伪造 exit_code、OBSERVED 或 PASS。
PID 消失、等待时间、部分 stdout 和“没看到成功”均不足以证明可重试；证据不足仍保持未决。

结果为 `BUILD_ATTEMPT_RESOLVED_NOT_EXECUTED`；派生状态 `RETRY_ALLOWED` 不改历史
UNKNOWN/失败事件、不验收旧输出、不退还预算、不创建新批准或执行目标。
下一次 advance 仍检查有效范围、剩余预算和全部独立 Case。
同一目标的新 scope 不能绕过旧 scope 的 IN_FLIGHT/UNKNOWN。
正常耐久观测恢复不需要使用此入口；它不是新增的逐 Workpack 人工门。

### 已完整捕获的重连误判：重判后只完成原检查

部分 Codex exec 版本把连接重试发成顶层 `error`。接收器按已核实的重连消息格式兼容
数字 n/m、不同错误详情、等待网络及计数重置；未知错误、失败终态、非零退出、真实流缺失、
超时仍保持失败或未知。完整成功终态与适用操作结束只证明模型过程完成，不证明产品接受。
合法 `declined`／空退出码表示命令被拒绝而未执行，单列诊断，不当成功或未结束。
通知总数完整计数；有界明细的截短不使完整原始流变成失败，也不增加生产尝试。

旧运行器已记录的同类 `MODEL_PROCESS_FAILED` 可用 `reassess-build-attempt`，
不能通过改 SQLite、覆盖 `result.json` 或新建 Program 清零。宿主绑定当前有效 prepared、
同任务最新旧尝试、原捕获及本次待验文件，沿既有真实处置消息结构提交：
`decision.action=REASSESS_BUILD_ATTEMPT`，`actor` 与 `user_message` 同上。
这是对具体旧失败的恢复处置，正常运行和完整报告取回不增加逐次确认。

`evidence` 精确包含：

- `runtime_identity`：`build_reassessment.runtime_identity()`，只绑定重判与观察实现。
- `capture_files`：`capture_identity(command)` 返回的原附件 SHA-256／字节数。
  包括 binding、capture、result、stdout，以及存在的 stderr、started、model-configuration。
- `artifacts`：原计划全部输出的 artifact_id 到 path／size／sha256 映射。

输入、检查器、有效授权及已接受依赖仍沿 `_current` 和原恢复路径检查。旧 BLOCKED，
以及旧版本记为 REJECTED 的实际进程误判可用；ASSERTION 失败、结果不完整、未知效果、
已开始验证或已有更新尝试不能借此变成通过。有配置声明时必须存在并一致绑定原配置回执；
未声明配置的历史命令保持兼容，不能从今天的默认值补写过去。

返回 `BUILD_REASSESSMENT_RECORDED_NOT_ACCEPTED`。它只原子追加纠正观察、绑定待验输出
与同一次尝试待检查状态；不调用模型、不运行检查、不接受输出、不增减原生产消耗。
随后 `advance-build` 可沿原流程只补未启动的独立检查；要仅交回这一项，使用既有
`advance_mode=ONE_ATTEMPT`。完整检查捕获只取回；启动后结果未知时核对原 command，
不得自动重发。真实 LOCAL 检查的时间、命令和结果照常记录。

同批准内、不改变原任务结构／检查的内部 Plan 调整复用既有适配判断，不机械要求整个
proposal ID 不变。原命令保持旧绑定；合法调整后的新接受记录注明当前验收 Plan，
并以 `implementation_proposal_event_id` 保留原实施来源。改变检查或外部范围仍按原规则处理。
旧失败可能没有结束时的输出快照：当前文件摘要只绑定本次待验字节，不能据此声称退出后
从未变化；宿主应据已有证据确认来源，或明确将当前文件纳入这次恢复处置。

同键同请求只取原回执，同键异请求冲突，改键不能重复纠正已处理尝试。原失败、模型消耗
和报告全部保留，`read-build --json` 的 `command_reassessments` 并列显示旧结果和纠正结果；
`reassessment_pending` 仅表示原检查待完成。撤销／过期不阻止纯回执取回，但不能继续检查。

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


## 显式同 Program 接续

2026-10-16：现有 `prepare-build-authorization` 请求可选顶层 `rebind_from`，其值为同一
Program、同一控制库的原 prepared_event_id。它不属于 scope，不新增命令或批准种类；
未选该字段的普通准备仍按原范围工作，不隐式合并任意历史。

本入口用于精确保留原额度的重新绑定：同 workspace，保持任务 ID、Job、产物声明及依赖，
并保持原 `max_attempts`、`max_task_attempts` 上限。已用次数按关联链中唯一真实 attempt
及原 budget_workpack_ids 累计；不是成功任务数或模型请求数。
例如原总额 24、任务上限 3，WP-H 已用 1，接续仍传 24/3，余额为总额 23、WP-H 2、
其他未开始任务各 3。不要先把总额改成 23 再扣旧消耗，也不要统一把其他任务减到 2。
NOT_DISPATCHED 已发生的消耗保留；读取、恢复和同一原始请求幂等重试不重复计入。

沿用原文档/来源准备、完整 Readback 和真实批准。在新批准的单次事务内记录旧新关联，
关联旧范围进入 SUPERSEDED，不能再派发同一余额；旧事件、报告和批准原文保持。
旧范围已撤销或自然失效可作为历史来源，不要求形式性重复撤销。
原 UNKNOWN/IN_FLIGHT 必须先核实，不因重新绑定取得清除资格；旧已结束的 BLOCKED
作为诊断历史交付，不直接成为新范围自动阻断。新范围的设施问题仍按原规则处理。

原要求、相关来源、实施声明、检查绑定和产物身份均适用的 accepted，可保留实际来源；
仅判定绑定变化时建立待复验项，advance 只执行必要检查，不伪造新的实施命令。
待复验在多次明确接续中继续保留。每次真实复验按原 attempt 规则计费，记录
`reverification_of_attempt_id`；恢复同一复验只补未派发检查。复验若发现业务断言失败，
仍由原生产者按原生预算修复；设施错误不冒充产品返修。
正常执行和恢复保存检查输入前，都核对声明产物与原接受字节；已有输入记录也须对应原接受。
已完成预检或已有检查观察时，字节改变或缺失返回诊断，保留该尝试；还原原字节可续验，
不重跑已完成预检或实施。无任何命令意图的预留仍按上述 NOT_DISPATCHED 规则处理。
旧版本已记录的错误检查输入不改写，也不能靠恢复把新字节变成旧接受。
实施要求或相关输入变化、产物字节不再适用时不复用旧 PASS。合法替换后已消费的旧物理版本
继续按原规则处理；新检查确需不可用版本时保留缺口，不能重放旧生产动作假造历史。

`read-build` 在接续范围展示 `rebind_from`、`reused_acceptance` 的原 prepared/proposal/attempt，
以及 `reverification_pending`。budget 展示累计消耗与 `this_preparation_attempts`，并给出未开始
原任务的余额。历史范围标明 `superseded_by`；不能从历史行选取新的可用余额。
任务上下文的 repair_history、反馈、预算和合法 handoff basis 使用明确关联链；无关 prepared
及跨 Program 的旧 basis 仍不接受。普通跨任务 handoff 规则、G1/G2 和同范围 replan 保持。

该接口不迁移跨 Program/跨库状态、不为任务改名或扩展 G1 continuation 链；旧记录仍可读。
数据关联不授予旧权限，当前绑定、来源、到期、读写域和真实批准在派发时继续核对。

## 按实际 Case 交付检查协议

实施上下文的 `verification_interfaces` 只投影本任务引用的公开接口：Case、resource_profile_ref、
result_protocol、required_checks、report_files、符号环境变量和适用的附加报告义务。
不复制完整 scope、保护预期、checker_files 内容或凭据/凭据引用，不扩大权限。
资源模式输出已有 STRUCTURED_V1 summary；非资源检查沿用原 stdout 或退出码合同。
公开开发 adapter 与私有独立检查器职责分别说明，实际独立执行须加载保护副本。


## effects 与正常构建链接

effects 观察已声明写根和具名保留文件，allowed 是精确允许变化的路径，不是扫描白名单。
普通目录继续遍历；末级软链接用 lstat/readlink 记录链接自身及原始目标字符串，不跟随目标。
正常 framework 链接、悬空或成环链接不会因递归跟随而阻塞，但链接目标是否有效仍由独立检查判定。
链接创建、删除、重定向和类型替换仍按原 allowed 比较；required/must_preserve 的普通文件义务
不能由链接冒充。末级链接不扩大读写根，通过软链接祖先访问子路径仍不允许。
首次构建可创建缺失的正常父目录；不新增忽略 build、通配授权或额外预检要求。

## 可选：完整准备后一次确认

完整合同与运行条件已经齐备时，可以用 `preview-build` 保存一次完整预览。它只写宿主准备文件；资源模式会在所声明控制库旁的 `.verifiers` 区域创建受保护检查器副本，不创建 Program、不创建目标目录、不启动模型或业务命令。原先“先确认合同、再准备并批准运行”的路径继续保留，已批准记录无需补做预览。

调用方式：`hffactory preview-build --control-db /absolute/host/control.sqlite3 --request /absolute/host/preview-request.json --json`。请求字段为：

- `preview_path`：新的宿主准备文件绝对路径；旧版本保留，不覆盖。
- `document`：`document_id`、`version`、`documents`；每份文档包含 `source_id`、`path` 和完整 `text`。
- `requirement_ir`、`plan`、`source_root`、`manifest`、`scope`：与既有入口相同的完整声明。scope 中的到期时间为绝对时间，不在确认后重新起算。
- 可选 `follow_codex_defaults`：沿既有规则将当前默认模型冻结；日常跟随则保持 `CODEX_GLOBAL_DEFAULTS`，不是强制所有任务冻结模型。

返回的完整 `readback` 绑定公开合同、来源、计划、模型策略及服务、工具、读写域、独立检查器、预算和有效期。完整内容由可信宿主展示；私有预期不能作为实施模型的公开输入。`preview_sha256` 只绑定这份已展示内容，不是授权口令。

用户一条真实消息明确同时确认该版本合同和运行范围后，宿主调用 `materialize-build-preview`，请求包含：

```json
{
  "preview_path": "/absolute/host/preview-v1.json",
  "preview_sha256": "从 preview-build 原样取得",
  "presentation": {"chat_thread_id": "实际展示所在会话", "turn_id": "实际展示轮次"},
  "decision": {
    "action": "CONFIRM_BUILD_AND_RUNTIME",
    "actor": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "同一会话", "turn_id": "后续真实用户轮次"},
    "user_message": "原始用户消息，不由模型编造"
  },
  "expected_revision": 0,
  "idempotency_key": "该次确认的稳定幂等键"
}
```

仅确认合同、继续准备、模型自我批准或引用旧版本消息，不构成合并运行批准。身份和消息语义仍由可信宿主核实；JSON 字段不能自行证明用户身份。平台权限不变。

物化依次登记完整预览确认、原 proposal、source、prepared，最后才追加运行批准。事件使用真实登记时间，批准依据明确指向已展示预览和真实消息，不声称用户提前看过尚不存在的 prepared ID。途中失败时用原请求、原 `expected_revision: 0` 和原幂等键接续；已经完成的阶段复用，不新建 Program 或重复捕获、准备、批准。变化的内容需要重新展示；已完成物化的取回不重新执行。

`BUILD_PREVIEW_MATERIALIZED` 仅表示该预览已形成绑定，不表示业务已执行或当前授权仍有效。随后使用返回的 `prepared_event_id` 和最新 revision 调用原 `advance-build`；派发继续检查有效期、撤销、当前范围和累计预算。原 `read-build` 可取回持久化预览、批准依据和现有运行记录。

本路径不增加审批步骤；其目标是将已有两次等待在完整材料齐备时合成一次真实决定。同范围宿主修正仍走对应接续入口，不能借一次确认扩大合同、服务、权限或预算。

## 同范围宿主修正与技术误阻断

这些入口只供可信外层宿主调用，目标实施模型不能写控制库或批准自身。JSON 是核实结果的记录，不认证调用者身份，也不能证明任意代码语义等价；宿主必须先核对具体差异、公开合同与独立预期。原人类处置与独立新批准入口保留。

检查器等义修正先另存修后文件，沿原 `rebind_from` 准备新的受保护绑定，再调用 `derive-build-correction`。请求除公共 revision/key 外含 `program_id`、新 `prepared_event_id` 和 `evidence`：

- `review`：`policy: SAME_SCOPE_CHECKER_CORRECTION_V1`，`actor: {type: TRUSTED_CODEX_HOST, chat_thread_id, turn_id}`，非空 `reason`、`evidence_refs`，`decision: EQUIVALENT_CHECKER_CORRECTION`。
- `source_prepared_event_id`、原样读回的 `old_verifier_files`、`new_verifier_files`，以及完整 `preserved_case_ids`。
- `changed_files`：每个实际变化的检查适配文件对应 `{role: CHECKER_ADAPTER, reason: 具体修正理由}`；包含必要代码依赖。改答案、删断言或改业务判定不能伪称适配修正，须回原决定流程。
- `completed_attempts`：一般接受／待复验复用可为空对象；尚未接受的原生产者按 attempt ID 列出 `artifacts` 和 `effects`。effects 含 `status: EFFECTS_RECONCILED`、完整 `command_ids`、`detail`、`evidence_refs`。宿主须核实实际效果，文件未变或进程消失不代替此事实。

新绑定仅继承仍有效的原真实批准，保留原生产目标、公开来源、断言、工具与服务、读写域、预算和绝对有效期。新检查有独立子 attempt，记录 `SAME_SCOPE_CHECKER_REVERIFY_V1`、原生产身份和本次检查器；只检查当前绑定产物，不重放实施。原失败保持，真实检查通过后才接受。新路径不新增生产消耗，但所有检查命令与耗时仍记录；旧版本复验已耗次数不退回。普通新人工重新绑定仍保留原计数语义。

来源批准及自动派生链中的撤销会停止后继派发，并沿原取消观察处理本次自有进程；旧 prepared 被替代本身不撤销来源批准。独立新人工批准不继承无关旧授权撤销。完整报告取回不需要重新授权或执行。

对实施阶段已有完整结束与效果证据的技术误阻断，可调用 `resolve-build-technical-attempt`，请求含 `program_id`、`prepared_event_id`、`attempt_id`、`evidence` 和公共 revision/key。evidence 含：

- `review` 形状同上，policy 改为 `HOST_TECHNICAL_DISPOSITION_V1`，decision 为 `TECHNICAL_FALSE_BLOCK_CONFIRMED`。
- `classification: TECHNICAL_FALSE_BLOCK_PUBLIC_SCOPE_COMPLETE`、原 prepared 中的完整 `public_basis: acceptance_contracts`、该次实际 `command_ids` 及同形 `effects`。

宿主应从公开范围和原始观察核实不存在待用户决定的真实缺口；不能仅凭模型把问题叫作“技术问题”。处理只登记 `RETRY_ALLOWED`，不接受旧产物、不增加授权、不退回用量；后续生产仍受原剩余额度限制。已有检查失败不通过该入口重放，检查器修正走上面的独立只复验路径。真正用户停止、范围／合同变化、未决效果、过期／撤销和不完整捕获均不能借此绕过。

同一请求使用原 revision/key 取回原记录；完整捕获只取回。新复验即使在首条命令前中断，也保留原复验身份，继续尚未派发的预检／检查。需要真正修复产品时回原生产者并扣原剩余额度，不扩大 G1/G2。
