# Harness Foundry v2.9 Implementation Tracker

截至 2026-09-20 的公开摘要见 [源码更新说明](FOUNDRY_UPDATE_2026_09_20.md)。
下文按时间保留工程快照；较早的“门禁待实现”“M1 未运行”等状态由后续同主题记录更新，
不表示当前状态。`build/`、`runs/` 和私人 Case 的证据引用仅用于本地追溯，不随 Git
或发行包公开，也不是他人可以直接执行的批准。公开回归可由仓库测试复跑。

Scope note (2026-09-18): the status and completion rule below concern the
41-capability core only. They do not close the user's updated goal of building
and accepting usable Codex-carried Harnesses. Forward work and its unimplemented
acceptance gates are in the [generic update plan v0.2](FOUNDRY_GENERIC_CODEX_HARNESS_UPDATE_PLAN_v0_2.md).
No existing completion evidence, authorization or runtime state is changed by
this planning note.

## v0.2.0 发布与用户文档 — 2026-09-22

2026-09-21 已按用户明确批准的范围完成正式发布：main 与 v0.2.0 tag 当时指向
`b1b1d41`，必需远端 CI 240/240、零 skip，私密漏洞报告启用，原 ZIP 上传后下载
字节一致，包外隔离 Python 的 version/help 通过。正式地址为
[v0.2.0 Release](https://github.com/alexYG-arch/Harness_Foundry/releases/tag/v0.2.0)。

2026-09-22 用户要求 GitHub 增加使用、依赖、场景与案例说明，并移除对外验收范围。
首页和本版说明改为用户导向，新增 USER_GUIDE；内部验收计数/阶段编号不再作为介绍主体。
工程历史、运行合同与原始证据保留；必要平台/工具限制仍公开说明。
本次只更新文档及 Release 文字，不改运行代码、版本、tag 或 ZIP，不触发新的模型建设。

## v0.2.0 发布收尾 — 2026-09-21（本地准备，不是远端发布）

补齐发布说明、版本/兼容性/支持限制、MIT 与依赖说明、安全报告政策和最终清单；
README 与开发 Manifest 区分“同包范围通过”和“远端发布未闭合”。发布范围见
[v0.2.0 清单](releases/v0.2.0-checklist.md)，不增设目标运行或逐 Workpack 批准。

本轮只改非打包说明/开发元数据；已验 `3c52c30` ZIP 不替换，35 个映射成员与当前源码
字节一致，归档身份仍为原 H1。公开源码门禁再次 240/240，零 skip；规范 101 文件、
Skill 4 引用复核通过，未重新运行完整兼容套件或真实模型案例。
默认 Python 缺少声明测试依赖的失败保留；原测试环境随后发现新增发布文档的离线断链。
链接明确改为不随包分发的开发仓库在线记录后通过，未改打包器、Verifier 或回归断言。
最终报告：`build/release-3c52c30/release-final-source-checks-r3.json`。

只读远端核对：正式 main 是当前源码祖先，没有分叉；无 tag/Release/Actions 运行记录，
私密漏洞报告尚未开启。仅 fetch 更新本地远端引用，没有推送或修改远端。
下一步需一次明确发布批准，覆盖正常快进 main、开启私密漏洞报告、相同提交 CI 通过、
v0.2.0 tag/Release 及原附件上传与下载核对；不得把当前清单作为实际批准或远端 PASS。

## 同包双案例 v0.2 — 2026-09-21（已批准最小端到端范围通过）

用户实际批准已展示的双案例最小运行范围 v0.2。固定提交 `3c52c30` 的 35 文件通用包，
在系统用户临时目录下完成两例真实建设和新会话使用；全程未换包、改绑定检查器或追加预算。
Task H/U/E/F 最终接受（revision 50，5/8 次尝试）；CSV H/U/E 最终接受
（revision 32，3/6 次尝试）。共 4 个不同的 GPT-6 Astra 会话、8/14 次尝试。

Task 25、CSV 13 组独立业务观察通过；U 形内部 workdir 和 E 形外部 workdir/只读 app
均实际运行，分别 8、6 个项目测试通过且无 skip。错误业务副本均被生成 Harness 以
ASSERTION 拒绝，受保护源码不变；CSV 原测试、API 和用户笔记保留。
宿主核对了需求映射、原始会话中的实际 Harness 读取/调用、完整对象行为与证据边界，
不是单凭 PLAN_CHECKS_ACCEPTED 自动宣称全产品或正式发布通过。

Task 模型成功落盘后实际触发宿主 exit 86；新宿主在原库中恢复同一 H command，H 只有
一次实施，独立验收后才启动 U。预定 E 合成缺陷拒绝保留，撤除一次性故障后复验真实 app
并自动推进 F。此处不冒称模型修复天然业务 bug；本轮未触发上游 repair_artifact_ids
分支，不把它列为新增原生证明。已有相应源码回归仍是该分支证据。

未发现本次已批准验收范围内尚未解决的交付缺陷。完整本地报告、控制库及原始过程附件
保全在 `build/release-3c52c30/execution-v02-20260921/RESULT.md`；副本不产生新运行授权。
本轮未修改产品代码、未重新跑全量源码测试、未推送/tag/发布，正式发布仍需最终清单与
明确发布决定。本机双案例通过不宣称全平台或真实第三方试用通过。以下旧失败快照保留。

## 跨阶段修复 — 2026-09-21（源码修复，不追认旧案例）

依据用户更新的侧聊修复方案实施：通用测试目录/解释器绑定与结构化错误、独立检查指定
上游 artifact 的原范围修复、发布适配器源码化及 MODEL_TURN_COMPLETED 恢复探针。
没有修改旧包/控制库/绑定检查器，没有新增真实模型尝试或继承耗尽预算。
Task/CSV 原业务判定函数保持不变，新增正常/错误与 U/E 组合检查，不以放宽 Validator 闭合。

定向最终 85 项、公开源码 240/240 零跳过、原生离线 U/E 只读边界验证通过；spec 101 文件、
Skill 4 引用通过。全量启动快照 962 项：942 通过、20 opt-in 跳过，835.067 秒；之后新增
3 项适配器回归由最终定向/公开门禁覆盖。保留 SQLite ResourceWarning，不把跳过计作验收。
详细范围、证据及未关闭项见
[跨阶段修复记录](FOUNDRY_CROSS_STAGE_REPAIR_2026_09_21.md)。
当前仍未正式发布；下一真实运行需新固定附件及展示后的有限范围批准。

## 同包双案例真实运行 — 2026-09-21（以下保留失败快照）

用户已明确批准双案例最小运行范围 v0.1；真实后续消息由宿主核对并通过公开 CLI 记录。
使用固定 24a0172 附件，共 4 次真实 GPT-6 Astra 会话和 4 次 LOCAL 实施，没有换包、
追加预算、修改绑定 verifier、推送或发布。两例 H/U 完成计划中的资源/源码前置检查；
E 均两次拒绝后到达逐任务上限，最终 `TASK_REPAIR_BUDGET_EXHAUSTED`，各 revision 41。
H/U 的 ACCEPTED 不是完整 Harness 验收。正式发布仍未闭合。

已取得可保留的实际行为证据：Task 真正 app 的 25 条 CLI 观察、CSV 的 13 条观察通过
原业务断言；Task 生成的行为检查入口也在 E 独立目录通过。CSV 原 summary API、原测试
与用户笔记保留。两个后继 Codex 会话确实读取并使用了各自 Harness 规则。

本次共性阻塞为阶段组合缺口：生成的检查入口拒绝 app 内 workdir，U 因其写域不能调用；
生成的单测反而硬编码向 app 写临时目录，到了只允许写 scenario 的 E 环境产生权限错误。
本轮外部验收适配器将嵌套错误概括为 ASSERTION，控制器于是重复无法修改上游产物的 LOCAL E；
不能靠增加 E 次数闭合。需要修复测试目录接口、跨阶段可用性预检和错误/修复归属。

另一个独立的本轮宿主测试编排错误：恢复中断脚本只识别 PASS，而真实模型成功为
MODEL_TURN_COMPLETED，故预定中断未发生。恢复窗口标为 NOT_TESTED，不把正常后继执行
当成恢复证明，也不宣称 Foundry 恢复实现已被证实失败。该脚本不在发行包内。

原失败、来源与控制库不改；已停止实际运行。完整本地报告和停机后证据保全副本在
`build/release-24a0172/execution-20260921.os1jhZ/RESULT.md`。修复后须展示受影响的绑定/预算
差异并取得新运行范围批准；本次批准不沿用为检查器变更、额外尝试或发布授权。

## 发布闭环当前摘要 — 2026-09-20（以下保留历史快照）

### 来源已固定、同包范围已准备；仍待真实运行批准

本地提交 58772ea 收拢此前已验的通用改动；随后同包离线预检发现当前 macOS 原生接收器
在共享 `/tmp` 中没有保护声明为只读的目录，显式 read/deny 的对照也仍可写入。
这是真实目录适用性问题，不是新的业务要求，也不能靠目录迁移宣称平台问题已修复。
提交 **24a0172** 增加共享临时目录布局的准备/批准/派发前拒绝，涵盖控制库、验证器、
源文件、运行代码及目标；别名解析后检查。保留普通目录行为，不加 Hash 或新的人工门。
当前仍不声称禁绝原生平台的所有基础临时文件写入。

验证：定向 71/71、公开源码 215/215（零跳过）、明确绑定 Python 3.13 的原生离线
接收器 10/10；完整回归 **939 项：920 通过、19 历史 opt-in 跳过、0 失败**，968.385 秒。
spec 101 文件及 Skill 4 引用复验通过。原生测试首次误用工程 venv，启动被拒的日志保留；
按拟定运行范围的基础解释器重跑通过，不更改断言或授权范围。
日志在 `build/release-58772ea/shared-tmp-{focused,source,full,native,native-r2}.log`；
这些仍不是目标模型执行或正式发布验收。

唯一当前待验附件为 **Harness-Foundry-0.2.0-generic-24a0172.zip**，来自完整提交
`24a0172f3b91a57b8b78a952b7f25b33adc00d28`。34 文件清单、MIT、无第三方 Python
运行依赖、独立解压加载、归档与解压字节一致及公开材料副本一致均已核对；
旧 58772ea 附件保留为历史，不继续验收。包与报告在 `build/release-24a0172/`。
产品版本 0.2.0、协议 2.9 不变；没有推送、tag 或上传 Release。

沿用已确认双案例搭建文档 v0.1，完整正文未改；只迁移实际输入位置并记录原位置、
副本和全文相等，保留原真实确认，不改写旧 Review。两份新控制库已完成提案/来源/范围
准备，状态均 `APPROVAL_REQUIRED`；目标目录不存在、模型调用为零。
Case 为 `RELEASE-24A0172-TASK` 和 `RELEASE-24A0172-CSV`。完整路径、模型、工具、
预算、到期和 prepared event 均记录在本地运行范围 v0.1；位置见
`build/release-24a0172/READINESS_REPORT.md`。这只是准备，不是运行授权或接受。
下一步只需要一次该具体范围的真实批准，不重复业务文档 Review、不逐 Workpack 批准。

### 本轮最小差量测试：3 项已执行

用户要求“压到最小test并执行”。本轮没有产品源码修改，沿用既有全量、公开源码、
M1 与重入结果；不新建业务案例、不重新运行旧全量、不增加故障注入或 Hash。
仅执行旧公开入口停用、隔离包加载/Review 门禁、包内两个依赖本地任务的独立检查与
不重放续跑，**3/3 通过，0 skip，0.895 秒**。日志：`build/minimal-delta-20260920.log`。
末项使用真实 Python 子进程与临时产物，不调用模型，不证明原生模型隔离或当前包的
真实 Harness 端到端验收。没有创建实际目标、复用旧运行批准、推送或发布。
这是本轮差量回归的完成，不是删除已确认的发布业务合同或宣布双案例已验收。

### W1A 生产入口退役：用户决定已执行，源码回归通过

用户明确决定“停止维护旧的新建流程，使用新的方式”。开发公开 CLI 与模块入口统一
使用通用 Build；旧新建/生成/运行/打包命令直接报 `LEGACY_WORKFLOW_RETIRED`，
不读请求、不打开 Program，不提供兼容开关。包顶层旧 Python API 取消公开导出。
旧 authoring 库新增独立 `read-history` 原始快照只读入口，不迁移、重放或恢复历史权限。
通用包新增此中性读取模块，仍不包含旧 Producer/Validator/CLI/测试夹具。

AGENTS、Skill、README、CLI 文档和 Manifest 已改为单一路线。历史回归使用测试专用
入口保留原行为断言；旧 41 能力检查明确是历史基线，不是新版公开接口或发行验收。
当前公开命令集合、退役无副作用、模块入口防回退、历史原样读取、WAL 拒绝及 API
绑定有专门回归。不新增 Hash 或审批链。未触碰真实历史数据库、Candidate 或目标。

这是生产入口和分发边界退役，不声称开发源码内所有历史模块已物理删除。
下述“待用户明确”已被本决定解决；同包双案例及正式发布仍须实际验收。

本轮验证（非真实目标/模型验收）：

- 定向 65 项通过：`build/retirement-focused-20260920.log`；历史核心诊断 6 项通过：
  `build/retirement-core-focused-20260920.log`。
- 公开源码检查 **213/213 通过、0 skip**：`build/retirement-source-20260920.json`。
  无私有状态/sibling 的临时源码副本复验同样 213/213：
  `build/retirement-isolated-source-20260920-r2.json`。首轮副本遗漏 README 导致失败，
  仅补齐副本后重跑，未改源码或放宽检查；原失败报告和日志保留。
- 全量 **936 项：917 通过、19 历史 opt-in 跳过、0 失败**，877.071 秒：
  `build/retirement-full-20260920.log`。已有 SQLite ResourceWarning 仍保留，跳过不作验收证据。
- 规范 101 文件、仓库 Skill 4 引用校验通过；两个 Skill 的 quick_validate 通过，
  使用本机已有 PyYAML，不安装新依赖。通用包预检 34 文件通过；`git diff --check` 通过。

这些结果不批准双案例运行、目标安装、Git 推送或发布；版本和 `release_ready=false` 不变。

#### 决定前的只读检查记录（保留追溯，不再是待决项）

本次只读依赖核对确认，这不是再删除一组打包文件即可关闭的事项：

- `AGENTS.md` 与活动 Skill 仍要求默认 41 能力核心和可新建/生成的 Start Package
  兼容路线；`entrypoint.py` 对非通用命令继续进入旧 `cli.py`。
- 旧 `service.py` / `compiler.py` / `semantic_contracts.py` 消费固定三工程、公共 Skill
  入口和媒体合同。现有 41 能力的部分行为绑定旧锁、编译、authoring 与便携入口，不能
  把整个旧模块目录删掉，同时声称这些当前接口和验收选择器仍原样保留。
- 通用更新计划 §1.2 / §9 要求专项从生产路径退役，而非默认关闭或可选保留；新通用包
  的隔离已经通过测试，但它不能代表上述旧生产入口已经迁移。

建议下一步先明确兼容承诺：保留并迁移需求/依赖/授权/验收/恢复等通用行为，旧固定
Start Package/Candidate/三工程生产接口退役，历史数据只读保留；以通用 Build 承接新建。
相应更新入口指令、CLI、Manifest 和行为测试映射，不能简单删掉仍适用的测试或保留假 PASS。
这是公开接口兼容性决定，不是内部 Workpack 增加审批；尚未按此建议修改生产入口或测试。
此检查当时等待用户决定；现由上方实际决定和实现替代，不借旧全量 PASS 证明本轮结果。

### 后续源码推进：恢复空窗与固定提交组装

- **REL-09 / W4B/R3：** 修复三类可复现断点：仅预留 attempt 导致永久 HELD；完整实施
  观测后的缺输出未按正常路径进入修复；恢复提交前授权到期仍可能记录接受。修复前最小
  回归为 2 failure / 1 error，见 `build/release-recovery-before-20260920.log`。
  现在无命令意图的预留以 revision CAS 结算 `NOT_DISPATCHED`；命令意图和恢复只能一方
  先提交，迟到原调度器不会覆盖恢复/新验收。已存在意图却效果不明仍停止，不盲目重放。
  完整观测下缺输出进入原范围内修复；恢复提交再次核对当前授权、绑定与 revision。
  原预算累计不重置，未新增批准、状态库、进程身份保证或 Hash。
- **REL-10 / W6：** 新开发入口 `devtools/package_committed_release.py` 显式选择 Git 提交，
  从临时跟踪文件快照运行该提交自己的组装器；不消费脏工作区/未跟踪文件或回退当前
  组装器。产品/协议/许可元数据须一致；来源提交与归档 H1 一同返回，不加逐文件摘要。
  预检如实区分临时写入与无持久归档；不修改原索引/提交，不推送、不创建 tag 或发布。
  六项测试的提交均位于临时仓库，不冒充真实发行来源。当前真实来源提交仍未创建。
- 六项恢复新回归和六项固定提交新回归已加入；合并定向 **90/90**，公开源码门禁
  **205/205，零跳过**；core、spec 和 Skill 再次 PASS。完整回归 **928 项：909 通过、
  19 opt-in 跳过、零失败，804.381 秒**。SQLite ResourceWarning 仍保留，不宣称零警告。
  [完整日志](../build/release-recovery-committed-full-20260920.log)、
  [定向日志](../build/release-recovery-committed-focused-20260920.log)、
  [公开源码报告](../build/release-recovery-committed-source-20260920.json)。
  `git diff --check` 通过；跳过项不算原生执行或双案例验收证据。
  当前无双案例目标/模型执行；已确认的搭建文档不变，运行授权仍未准备/授予。
- 同一公开源码检查在无 sibling/私有状态的临时副本 **205/205** 通过。
  首跑因本次复制准备遗漏仓库内 `schemas/`、`spec_lock/` 失败；补齐原资源后复跑，
  未修改生产代码或放宽检查。两次日志分别为
  `build/release-recovery-committed-isolated-source-20260920.log` 与 `-20260920-r2.log`。
  R3 的闭合按既定故障窗口及其下一动作判断，不新加“任意故障自动恢复”或“重启后强杀
  未知 PID”要求；这些明确非目标不能无限变成下一轮发布门槛，具体停止仍需可解释证据。
- **保留的退役缺口：** 通用包已不载入旧模块，但开发入口 `entrypoint → cli → service /
  compiler → semantic_contracts` 仍可进入旧专用合同；`media_evidence_contracts` 及旧
  compiler 固定工具/阶段不能因此被称为已退役。后续 W1A 需处理这条实际调用链，同时
  保留既定核心 41 能力的通用行为和只读历史；不能仅删包清单、关键词或适用测试闭合。

R3 的有限恢复覆盖按下面可复跑行为核对，不按“具备任意进程修复能力”判断。
测试名位于 `tests/test_build_runtime.py`；另标注者除外。它们是源码/临时进程证据，
不替代待验发行包的同包场景。

| 故障窗口 | 已实现动作 | 直接回归 |
|---|---|---|
| attempt 预留，尚无命令意图 | CAS 结算未派发，保留预算；迟到调度器不能覆盖 | `test_reserved_attempt_without_command_intent_recovers_without_new_approval`、`test_delayed_original_dispatcher_cannot_overwrite_reconciled_attempt` |
| 已派发但无完成观测 | HELD，不重复派发；提示核对缺失事实 | `test_crash_after_dispatch_without_observation_is_held_not_replayed` |
| 宿主附件完整，控制观测丢失 | 核对绑定并补回观测，不重跑实施 | `test_native_receiver_attachment_recovers_before_controller_observation` |
| 仅部分检查已完成 | 核对同一产物，仅运行剩余 Case | `test_crash_after_one_case_resumes_only_remaining_checks` |
| 检查完成未提交 | 重核范围/到期与当前字节，提交或停止 | `test_crash_after_complete_checks_recovers_acceptance_without_reexecution`、`test_recovery_rechecks_expiry_before_acceptance_commit` |
| 提交完成后重新读入/推进 | 从 SQLite 投影视图，不重复效果 | `test_public_commands_run_real_local_fixture_verify_and_resume_without_replay`（`test_build_entrypoint.py`） |
| 活宿主撤销/到期；重启后只剩 PID | 前者终止自己持有的进程组；后者仅诊断，不据此杀进程或接受 | `test_revoke_stops_running_native_command_and_preserves_history`、`test_expiry_stops_running_native_command_and_preserves_history`；`test_live_pid_is_diagnostic_not_identity_or_replay_authority`（`test_process_observation.py`） |
| 缺产物、业务失败、环境/合同失败 | 业务在原预算修复；基础设施/合同问题停止对齐 | `test_recovered_missing_output_is_rejected_then_repaired_like_normal_execution`、`test_verifier_environment_failure_does_not_trigger_implementation_repair` |
| 已验输出变化 | 仅失效受影响任务与后继；保留无关分支 | `test_changed_accepted_output_rebuilds_only_affected_dependency_branch` |

### 后续源码推进：活宿主取消链路

- **REL-08 / W4B/R3：** 通用 `BuildController → NativeBuildRunner → LOCAL/CODEX`
  采集器传递当前授权检查。约每 0.25 秒检查撤销/到期，只终止本宿主持有的有限命令进程组；
  不按进程名或重启后的旧 PID 杀进程，不增加授权、事件 Hash 或第二控制状态。
- 修复关闭 stdout/stderr 后进入阻塞等待的分支，确保无输出时仍检查取消/超时。
  授权监测故障也保留原因并停止。取消不回滚副作用，耐久观测及恢复均保持未知状态；
  不进入业务修复重试、不接受旧产物、不释放后继，也不返还 attempt 预算。
- 新增真实本地进程取消、子进程组清理、关闭输出流、监测故障、正常完成对照、
  完整终态不能覆盖取消，以及控制器撤销/到期集成回归。Codex 使用明确的假服务进程，
  不宣称原生模型或 OS 隔离已验。定向 **81/81** 通过；公开源码 **193/193，零跳过**，
  核心 41 能力/26 selectors、规范 101 文件、Skill 5 引用再次 PASS。
- 另有本轮真实 macOS Codex 沙箱离线采集检查：临时 Python 命令写出部分文件后，
  宿主取消得到退出 -9、`LOCAL_PROCESS_CANCELLED`、未超时、部分文件保留；无模型调用。
  最初嵌套沙箱未能启动，其后开发 venv 的读取绑定不全也未启动负载；没有降级直跑。
  获平台许可后改用明确的原始解释器及其完整安装依赖，原生沙箱检查通过。
  这只验证取消接收器，不关闭真实模型、整套原生 opt-in 或同包案例验收。
- **后续实际用户决定：** 用户已明确回复“确认双案例搭建文档 v0.1”，确认 Task CLI
  完整 PRD 和 CSV 增量说明的业务、搭建及验收范围。被展示文档保持原字节（其中 DRAFT
  是展示时状态），不靠改写文档制造批准。此条是工程进度摘要，正式提案仍须通过公开接口
  绑定全文及真实展示/用户消息引用；本轮尚未创建双案例 Program、目标目录或运行批准。
  本地 `authoring_inputs/release-acceptance-v0.1/document-review.json` 已保存六份完整材料和
  实际展示/确认 turn 引用，`validate_build_review` 当前字节核对通过；它只是待提案消费的
  宿主输入，不是第二控制库或运行批准，也不随 Git/发行包公开。
- 文档 Review 已通过，不再重复询问相同内容。具体运行范围必须在精确待验发行物、
  独立检查器和依赖准备完成后展示；本轮无模型调用、Git 推送或发布。
  重启后进程身份/启动空窗、剩余恢复、生产入口退役及同包真实验收义务保持开放。
- **本切片完整回归：916 项，897 通过、19 opt-in 跳过、零失败，836.052 秒。**
  [完整日志](../build/release-cancellation-full-20260920.log)、
  [定向 81 项](../build/release-cancellation-focused-20260920.log)、
  [公开源码 193 项](../build/release-cancellation-source-20260920.json)。新增 8 项回归；
  源码门禁包含其中 7 项，另一个假模型接收器测试随完整套件执行。
  `git diff --check` 通过。19 项跳过不作为原生通过，SQLite ResourceWarning 仍保留。
  新取消能力没有改变 `release_ready=false`、既有 M1 接受结论或历史控制状态。

### 本轮继续推进：通用运行隔离与发布案例准备

- **REL-04 / W1A/W5B/W6：** 拆出 `identity`、`build_types`、`coding_events` 与
  `revision_store`；通用公开 CLI 不再导入旧 kernel、Hash Store 或专项 Producer。
  旧 Python 入口委托同一份共享实现，保留原 `REVISION_V1` 数据格式和历史语义，不迁移旧库。
  `devtools/package_generic_release.py` 显式收集 16 个通用模块及接入/许可/示例资源，
  实际归档 33 个文件；只对归档计算 H1，包内无逐文件摘要表。
  **通用包物理隔离已实现，但历史源码生产入口的完整退役和正式发布仍未关闭。**
- **REL-05 / W4A：** 未开始任务支持同 Job、同执行器、相同原写域内拆分/合并，
  独立任务可重排。原输出/版本链、Case 命令及产物绑定、依赖顺序、输入范围和预算保持。
  拆分共享原任务预算，合并向原任务分别计费；已开始任务不能靠改名绕过失败或未知历史。
  定向回归实际执行拆分/合并后本地进程，检验逐 Case、单次批准、不重放和预算停止。
- **REL-06 / 兼容回归：** 第一轮全量发现旧 Candidate 固定打包清单漏带抽离后的三个
  共同依赖，独立 Validator 返回 `PORTABLE_RUNTIME_DEPENDENCY_MISSING`。修复 Producer
  的全部相关运行包组装入口，不放宽 Validator；新增实际迁移导入及删除依赖仍失败的回归。
  随后发现旧精确文件集合断言尚未列入这三个必需文件，已更新集合并增加逐文件字节核对。
  两次中断的完整运行日志保留，不列为完整 PASS；最终整套复验另记结果。
- **REL-07 / W7A/W7B 准备：** 已输出[双案例搭建文档 v0.1](RELEASE_ACCEPTANCE_BUILD_DOCUMENT_v0_1.md)
  和完整公开 Task CLI PRD / CSV starter 增量材料，等待真实 Human Review。
  未创建这两个 Program/目标目录，未运行模型、未借旧 M1 批准。文档确认不等于运行授权。
- 当前公开源码检查在本仓库和无 sibling/私有状态的独立源码副本均为 **186/186，零跳过**。
  新包在实际解压目录通过隔离 Python 导入、CLI/Review 门禁、真实临时本地进程检查和续跑；
  迁移后的 Skill 经 skill-creator 检查通过，CSV starter 原有 2 项测试通过。
  这些仍不证明实际模型、新用户接入或同包双案例已经通过。
- **最终稳定切片验证：908 项，889 通过、19 opt-in 跳过、零失败，762.434 秒。**
  [本地完整日志](../build/release-generic-full-20260920-r3.log)；核心再次 PASS（41 能力 /
  26 selectors），规范 101 文件、仓库 Skill 5 引用 PASS。`git diff --check` 通过。
  19 个跳过项不等于原生运行通过；已有 SQLite ResourceWarning 仍保留，不宣称零警告。
  定向新增 21 个通用分发/重规划/旧依赖闭包回归；实际 Skill 校验使用现有本地校验依赖，
  未新增发行运行依赖。临时工程归档和源码副本仅是工程验证，不是正式交付附件。
- 正式仓库只读 API 本轮已成功查询：Release 和 Tag 列表均为空；没有创建/修改远端内容。
  私密漏洞报告的开启仍待此前提出的用户决定，不代选联系方式、不虚构已开启。

**下一真实门禁：** 双案例搭建文档现已由用户明确确认；从最终候选准备完整
运行范围后取得真实批准。还需闭合历史生产入口处置、约定恢复/取消边界、干净来源版本、
同包真实验收、远端 CI 与最终发行决定；`release_ready=false`，不因本轮测试增加而上调。

### 本轮之前已完成的发布准备（保留证据）

- 用户选择 MIT；正式仓库固定为 `alexYG-arch/Harness_Foundry`。已添加许可正文、
  Python 许可/仓库元数据和[发布准备说明](RELEASE_READINESS.md)，没有修改远端或发布。
- 只读复核现有 M1 控制库与执行报告：限定 A/B/C 和独立新会话 D 均 ACCEPTED。
  实际建设、使用、持久场景及重入的证据保留；B 的会话内修复不等同于控制器重新派发。
  旧失败不删，私有输入/原始会话不公开；`harness_e2e_verified=false` 保持不变。
- **REL-01 / W6：** Producer 的便携清单补入缺失的合同对齐文档、MIT 与发布说明。
  在实际迁移目录核对链接/许可及隔离 Python 的通用编译入口；缺文件在创建包前拒绝。
  这修复缺资源，不关闭旧专项尚被全量收集的 GEN-01。
- **REL-02 / W6/W7C：** 新增公开源码检查入口和 GitHub 工作流；必要项缺失、零测试、
  SKIP、xfail、断言或基础设施失败均返回失败。只输出诊断，不成为另一套批准/状态权威。
  在本地和没有规范 sibling/私人状态的临时源码副本中，166/166 通过，0 skip。
  首次新增迁移断言因系统临时路径别名失败，改为比较解析后的物理根后通过；失败记录保留。
- **REL-03 / W6：** README、Manifest 和当前接口说明不再错误声称 M1 尚未运行/验收；
  明确限定子流程与通用发行验收之别，历史报告只追加新进度，不重写旧授权或接受记录。
- W6 为 IN_PROGRESS；W7A/W7B 的最终同包案例、W7C 最终发布仍未关闭。
  GitHub 托管 CI 尚未运行，独立源码副本不是目标 Harness 的干净接入证明。

剩余工程按原依赖推进：GEN-01 专项与 GEN-02 旧 Hash 消费者退役 → W4 完整约定恢复/
计划适应 → W6 最终候选 → W7A/W7B 同包真实案例 → W7C 闭合。现有 M1 不无故重跑。
许可证/发布仓库的两项选择已解决；新案例文档 Review、具体运行范围和最终发布授权仍须真实决定，
不增加逐 Workpack 门。

本轮稳定源码验证：完整回归 887 项，868 通过、19 opt-in 跳过、0 失败，836.410 秒；
[本地完整日志](../build/release-closure-full-20260920.log)。核心 41 能力 / 26 selectors、
规范 101 文件及 Skill 5 引用均 PASS；既有 SQLite ResourceWarning 仍存在。
临时源码副本实际完成 Python wheel 元数据构建，MIT、LICENSE 文件和正式仓库 URL
进入构建结果；该测试不新增 wheel 发行路线、不全局安装或发布。
只读 GitHub 检查确认正式仓库为 public、Issues 可用、私密漏洞报告关闭；开启仍待用户决定。
查询历史 Releases/Actions 遇到 TLS 超时，未推断其不存在，未修改远端设置。

## Generic upgrade execution — 2026-09-18

### 后续修复：公开验收合同对齐 — 2026-09-20

- 根因：Case 的描述和验证命令之间缺少公开接口依据，检查器可能精确比较合同未规定的
  表示；空集合样例和数量-only 检查又掩盖了元素/身份差异。它不是增加模型次数能解决的问题。
- Producer/输入链：Case 绑定 `acceptance_contract`，来源采集解析其定位；新运行范围准备
  必须覆盖全部 Case，Readback 和实际任务上下文消费同一公开正文。旧提案仍可读取，
  旧范围不能凭本轮修复自动升级权限，历史不改写。
- 验证/控制链：领域无关的公开样例工具检测格式误判、只检查数量或全部拒绝；检查器崩溃
  不算正确反例。CONTRACT_GAP 分流为 HELD_ACCEPTANCE_CONTRACT，停止实施重试和后继，
  重入/观测恢复不改变该结论，也不退还已发生尝试。
- 工程回归：`tests/test_acceptance_contract.py` 及相关 Build 测试；合同/接口说明见
  [验收合同对齐](ACCEPTANCE_CONTRACT_ALIGNMENT.md)。本轮没有增加 Hash、数据库或逐包批准。
- 验证：完整 880 项（861 通过、19 opt-in 跳过、0 失败）；最后定向复跑 104 项全部通过，
  覆盖追加的恢复断言。核心 41 能力 / 26 selectors、规范 101 文件、Skill 5 引用均 PASS。
  SQLite ResourceWarning 仍保留；结果是源码回归，不是目标端到端通过。
- 边界：定位和样例通过仍不证明语义全覆盖；用户私有 Case 的新版接口/样例/独立检查器
  留在忽略目录，等待实际文档 Review 与新范围批准。源码回归不关闭 M1 或发行验收。

以下 2026-09-18 条目保留为当时的工程快照。

用户已授权“执行方案”。当前为源码工程执行，不是目标 Harness 的运行批准。
既有六个代码/测试文件与相关说明中的协议 V3 修改保留；本切片没有重写旧 SQLite、
锁、候选或事件链。原完整测试日志为 717 项（17 skip），仅作为旧基线。

### W0 最小接口与归属

| 边界 | 现有/新接口及唯一职责 | 后续归属 |
|---|---|---|
| 需求 | Requirement IR 的 Atom、Source、Case；来源/验收承诺不由计划编译器创造 | W1B / `service.py` |
| 可变实施 | `build_plan.py` 的 Plan revision、显式 Workpack/Job/产物/DAG；只读编译不进入旧固定项目路由 | W1A / 编译模块与 CLI |
| 授权 | `build_runtime.py` 同库范围准备/宿主批准/撤销；`build_entrypoint.py` 接公开 CLI，数字版本不是批准 | W5A/W5B / 通用控制器、`store.py` |
| 执行 | 新消费者重用 Codex/local 适配器与 attempt；命令结束不是验收完成 | W2/W4 / 通用控制器和现有进程适配器 |
| 验收 | 独立运行 Case、观测实际产物，由同库事务提交后才可消费前置 | W3 / 通用控制器；旧 evidence/acceptance 不混用 |

支持环境基线：当前 Python 3.11+ 标准库静态接口、JSON Requirement IR/Plan；
不声称已支持任意 PRD 格式、任意操作系统或真实 Astra 建设。
代表性样例按方案选择新建 CLI/API 与既有数据工具增量工程，真实运行仍为 NOT_RUN。

| 包 | 状态 | 当前证据/缺口与下一步 |
|---|---|---|
| W0 | DONE | 工作树基线核对；README/Manifest/AGENTS/Skill 与新旧完成范围对齐；下表 G1–G13 归属明确 |
| W1A | IN_PROGRESS | 通用 Plan 支持文件版本替换/读写顺序；CLI 不加载专项 Producer；已接固定提案的任务上下文。旧 Candidate materializer 与专项包引用尚未退役 |
| W5B | IN_PROGRESS | 新授权/观测/验收使用同一 revision 库，无事件摘要链；H2 仅命名 verifier/产物文件。旧专项消费者/包引用尚未退役 |
| W1B | IN_PROGRESS | 本地 MD/TXT/JSON 显式清单全文读取、Atom 行定位、来源变更失效已接通；语义缺口判断和完整 PRD 场景未闭合 |
| W5A | IN_PROGRESS | 公开宿主准备/批准/撤销/推进/Readback 及分路线指令已接；目录创建含于一次范围批准，真实宿主 M1 待运行 |
| W2 | IN_PROGRESS | Plan→现有原生 Codex/local receiver 已接；本地真实测试进程通过。真实 Codex/沙箱宿主 M1 未运行 |
| W3 | IN_PROGRESS | 外部只读检查、逐 Case/Job 观测、实际输出身份与 SQLite 验收提交已接；真实模型/发行验收未运行 |
| W4A | IN_PROGRESS | 两个依赖任务及真实本地失败→修复→接续通过；模型自主修复、完整故障路由仍待 M1/M2 |
| W4B | IN_PROGRESS | 完整观测后恢复提交且不重复实施；未知效果保持 HELD。部分检查续跑、选择性失效/进程核对未完成 |
| W6 | PLANNED | 静态接口说明随既有包收集；清洁通用发行物及 Codex 接入未验收 |
| W7A | IN_PROGRESS | 用户 PRD 的 M1 子流程、独立检查与具体范围已准备；真实模型执行/目标验收 NOT_RUN |
| W7B/W7C | PLANNED | 目标加载、第二样例、最终发行闭合全部 NOT_RUN |

### G1–G13 验收归属

| 要求 | 首要实现/回归入口 | 必须观察的完成证据 |
|---|---|---|
| G1 保留核心/生成/启动 | core validation、compiler/startup 回归；W0/W1/W6 | 核心 PASS + 通用生成/启动实测 |
| G2 剔除专项 | 通用 Plan、旧 compiler/semantic/validator/portable 迁移；W1A/W6 | 无专项生产依赖的实际包及两个业务样例 |
| G3 需求不漂移 | Requirement IR/接入审查；W1B/W5 | 资料可回答、关键歧义、合理默认、修正假设四类 |
| G4 实际 Codex | coding_process/runtime；W2/W3 | 实际模型事件和可用代码，不是 TEST 进程 |
| G5 合同与产物 | build_plan、artifact ownership、证据消费；W1A/W3 | 归属/依赖静态验证 + 实际当前产物匹配 |
| G6 独立判定 | workpack_acceptance/evidence；W3 | 行为错误被拒，控制器事务提交后发布能力 |
| G7 自主修复 | control kernel / adapter；W4A/W5 | 两个依赖任务、一次真实拒绝修复、预算停止 |
| G8 恢复 | controller/checkpoint/process；W4B | 派发/观测/提交中断不重复效果 |
| G9 授权 | Parent/平台；W5A | 范围内连续，扩权/撤销/过期/未知结果停止 |
| G10 包级交付 | portable/onboarding；W6/W7 | 实际包无开发机隐含依赖 |
| G11 PRD 适配 | 来源理解→需求→Plan；W1B/W7 | 新建及既有工程的真实开发/增量结果 |
| G12 最小 Hash | 版本/事务/必要字节身份；W5B/W6 | 全链只保留 H1/H2，不靠 Hash 声称业务 PASS |
| G13 他人可用 | 干净接入环境；W6/W7 | 同一包凭公开说明完成建设和使用 |

### 当前未闭合项（同一账本）

- **GEN-01 / W1A：** 新静态 Plan 不注入专项，但旧 Candidate materializer、
  `semantic_contracts.py`、Lab public Skill 和媒体 Validator 仍可调用并被旧打包器收集。
  下一步迁移普通生成/任务合同消费者，再退役专项；不能以隐藏入口闭合。
  文件顺序修改合同已补齐：显式 `replaces_artifact_id`、前置输入、单链归属和旧版
  读取先于替换；本地控制器已验证替换失败后的修复顺序，真实 Codex 编辑仍待 M1。
  新任务上下文消费实际使用的提案事件并保留全文来源。
- **GEN-02 / W5B：** 新 Plan 已接入提案事务，整数版本、UUID 事件引用、原始 JSON
  幂等取代新提案链的摘要。旧 authority/event/receipt Hash 链仍在旧运行消费者使用；
  新授权/验收消费者、公开宿主入口和 H2 已接通，旧消费者退役仍未完成。
  不能将提案保存视作批准。
- **GEN-03 / W2/W3/W4：** 新 Plan 已有真实本地进程的执行/验收/推进消费者；
  真实 Codex、原生沙箱新路由、选择性重验/部分观测恢复未完成。
  不得把测试进程或模型自报当作真实 Harness acceptance。
- **GEN-04 / W1B/W6/W7：** 完整本地来源读取已接通，资料语义接入、洁净发行物和
  代表性真实 E2E 仍未实施。M1/M2/M3/M4 均未关闭。

### 首个实现切片验证结果

- 新增通用计划回归：16 项通过；包括缺需求/Case、错 Job/Workpack、依赖缺口、
  环路、路径冲突、输出投影增删/改绑、版本类型、只读 CLI。
- 独立复核复现了 `True == 1` 导致输出版本类型变化未被发现的问题；已改为
  JSON 类型保真的值比较并加入回归，不新增 Hash。
- 稳定版本全量回归：[完整日志](../build/generic-update.mqSeMY/full-final.log)：
  `Ran 733 tests in 980.636s; OK (skipped=17)`，即 716 通过、17 跳过。
  跳过项包括未配置的真实本地沙箱测试，不计作真实模型或 Harness 验收。
- [官方核心验证](../build/generic-update.mqSeMY/core-final.json)：PASS，41 项能力、
  26 个 selector；未创建 Candidate/Execution Root。
- `verify-spec` PASS（101 文件）、`tools/validate_skill.py` PASS（3 个引用）、
  skill-creator `quick_validate.py` PASS、`git diff --check` PASS。
- 新入口的临时迁移包冒烟 PASS：无规范 sibling、无 Program 状态，stdin 输入可完成
  `compile-build-plan`；不执行 Harness。它不是清洁通用发行物或 W6/W7 验收。
- 初始默认 Python 3.14 缺 `jsonschema`，首次完整回归因此中止；改用工程 `build/`
  下的独立 Python 3.13.3 环境，安装仓库声明的测试/可选依赖后重跑。
  [实际依赖版本](../build/generic-update.mqSeMY/test-environment.json)留存；全局 Python 未修改。
  另一轮回归为修正版本类型比较而中止，只有 `full-final.log` 用于此切片关闭。

该首轮结论仅为 W0 及 W1A 静态合同切片有效；M0–M4、完整 W1A、W5B 与其余工作包均未关闭。
没有提交 Git、推送、发布、真实模型调用或目标安装。

### 连续推进切片 — W1A/W5B

- `build_plan.py` 与独立输出校验同步支持产物版本替换；回归覆盖顺序编辑、
  旧版读取冲突、并行写冲突、缺失输入/前置、替换关系投影错误。
- `cli.py` 将旧专项 Authoring Service 限定为兼容路由按需导入；新 CLI 的测试
  主动禁止导入旧 Producer/Validator/traceability，仍能编译通用输入。
- `ControlEventStore(storage_format="REVISION_V1")` 沿用两表单库模型，实现
  SQLite 事务、expected revision 并发校验、原始 JSON 幂等、整批回滚；没有
  Hash 列/计算。历史格式默认行为保留，错格式打开在修改前拒绝，不迁移历史库。
- `build_authoring.py` 记录未批准提案、按事件重建 Plan、投影逐任务上下文，保留
  全局约束与全部任务 Case；修改实施计划不强制需求升版，需求内容变更不可静默覆盖。
- 真实 SQLite 并发、幂等、回滚和旧格式隔离均在临时测试目录验证；未创建真实
  目标 Program/Execution Root、未运行目标 Workpack。新上下文是声明，不是模型行为证据。
- 局部测试共 40 项通过（21 Plan、9 提案/任务消费、10 revision store）；联通测试发现
  返回事件对调用者嵌套对象持有引用的问题，已改为按持久化 JSON 值返回并复验。
- 稳定源码完整回归：[完整日志](../build/generic-progression.Yv5MHN/full.log)：
  `Ran 757 tests in 811.932s; OK (skipped=17)`，即 740 通过、17 跳过，零失败。
  跳过项仍为未配置的 opt-in 范围，不计入真实模型或 Harness 端到端验收。
- [核心验证](../build/generic-progression.Yv5MHN/core.json)：PASS，41 capabilities、
  26 selectors、findings 为空，未创建 Candidate/Execution Root；
  [规范校验](../build/generic-progression.Yv5MHN/spec.json) PASS（101 文件），Skill
  校验 PASS（3 references），`git diff --check` PASS。
- Python 3.14 的[计划/提案测试](../build/generic-progression.Yv5MHN/python314-build.log)
  30 项、[新存储格式测试](../build/generic-progression.Yv5MHN/python314-store.log) 10 项
  全通过；完整回归使用首轮隔离的 Python 3.13.3 依赖环境。
- 临时迁移包中的提案 API 冒烟 PASS：无原 workspace/PYTHONPATH 或 sibling 依赖，
  提案写入临时 SQLite 后可读取任务上下文；无专项模块导入、无目标命令运行。
  这是新 API 的包级冒烟，不是 W6/W7，包内尚有旧专项源码。
- 本切片不关闭 W1A/W5B 全包或 M0。通用共享提案合同已可供后续迁移消费，下一步
  是完整来源接入及建设授权/执行/验收消费者迁移，再退役旧专项生产和包引用。
  均按既定工作包连续推进，不新增人工“继续”门；真实模型/目标执行仍需实际范围授权。

### 连续推进切片 — 来源 / 授权 / 执行 / 验收 / 恢复

- `source_intake.py` 全文读取显式本地 MD/TXT/JSON 清单，保持原始换行；缺附件、
  不支持格式或不可解析行定位明确失败。没有联网、自动执行原文或 Source Hash。
  全部显式来源进入运行上下文；这不证明语义没有遗漏或未列附件已被发现。
- `build_runtime.py` 将范围准备/宿主批准、过程观测、逐 Case 验证、验收提交与
  后继调度接入同一个 revision 事件库。原生适配器复用既有 Codex/local receiver；
  公开宿主批准入口未提供，库函数的消息引用不能自行认证人类批准。
- 实现目标/命令在不改变需求、依赖、产物、验收及权限的范围内可重规划，不新增
  人工批准。有限预算、撤销、到期、源文件变化和未知副作用阻止后续派发。
- 本地真实 Python 进程验证了两个依赖任务、故意错误实现被拒后修复、显式产物
  替换和全 Case/Job 归属。任务的自报/模型完成事件不能代替独立检查。
- 检查已观测但未提交时，可从当前字节与事件恢复验收，不重跑实施；未观测进程
  或部分检查仍 HELD。选择性证据失效、部分阶段续跑与真实进程核对尚未闭合。
- 只读复核在临时 fixture 复现了“可写验证解释器被改为 exit 0，使错误结果通过”
  的缺口。已从范围生产校验处阻断执行器/receiver 的调用路径和实际目标落入任务
  写域，并加入具体复现型回归；没有增加全树 Hash 或放松 Validator。
- 定向测试：计划/提案/运行合计 58 项（22/9/27）通过，来源 17 项通过，本地
  receiver 合同 8 项通过（另 8 项真实沙箱 opt-in 未运行）。Python 3.14 的
  [58 项测试](../build/generic-runtime.X5YeU5/python314-build.log)和
  [17 项来源测试](../build/generic-runtime.X5YeU5/python314-source.log)也通过。
- 稳定源码[完整回归](../build/generic-runtime.X5YeU5/full.log)：
  `Ran 803 tests in 782.314s; OK (skipped=17)`，即 **786 通过、17 跳过、零失败**。
  使用既有隔离 Python 3.13.3 环境；完整测试期间没有改源码。
- [核心验证](../build/generic-runtime.X5YeU5/core.json) PASS：41 capabilities、
  26 selectors、findings 为空，未创建 Candidate/Execution Root；
  [规范检查](../build/generic-runtime.X5YeU5/spec.json) PASS（101 文件），
  Skill 引用校验 PASS（3 references），`git diff --check` PASS。
- 本机 Codex CLI 的 version/help 只读核对确认既有 exec/sandbox 接口可见；没有
  把 help 结果当作真实沙箱应用、模型账号可用或 Astra 任务执行的证明。
- 结论仅为库级局部工程链路成立：**M1/M2/M3/M4、完整 W1–W7 未关闭**。后续优先
  接公开建设/宿主批准路由，准备 M1 的具体根目录、模型范围和预算，取得实际运行
  范围后尽早真实联通；同时继续退役专项包依赖，不回到反复生成静态 Candidate。
  本轮没有真实模型调用、目标安装、Git 提交/推送或发布。

### 连续推进切片 — 公开 Build 宿主入口与真实 M1 准备

- `build_entrypoint.py` 与公开 CLI 已连接提案、完整来源、范围准备、真实宿主
  批准/撤销、推进和只读 Readback。后者包含完整 Requirement/Plan 及源读取范围，
  不把消息结构或 actor 标签当作身份认证。历史控制库只读拒绝混用；无旧批准继承。
- 目标可不存在；只有批准后的 advance 创建目标/任务目录，父目录必须已存在，
  不在范围外补建祖先。没有单独的“批准创建目录”或逐任务确认门。
- 大来源使用完整只读文件引用，原文进入同库且派发时比对，不再重复塞入模型
  prompt，也不截断/摘要代替。加载全文不等于完整语义审查。
- AGENTS、Skill、UI 提示、README 和 [公开入口合同](GENERIC_BUILD_CLI.md)已区分
  core、兼容 authoring 和显式 generic Build。默认/兼容路线仍不因新入口而自动执行。
- 定向 [71 项测试](../build/generic-entrypoint.GV6VIE/focused-final.log)通过；
  [默认 Python 3.14 的同组 71 项](../build/generic-entrypoint.GV6VIE/python314-build.log)
  也通过。覆盖公共命令、真实本地 fixture 接续、批准前零目标写、伪 actor 拒绝、
  过期/撤销/并发、原始请求幂等、旧格式隔离和大来源完整可读。
- 本次[完整回归](../build/generic-entrypoint.GV6VIE/full.log)：816 项、984.684 秒，
  **798 通过、17 跳过、1 失败**。唯一失败是 Skill UI 文案遗漏默认路线的
  `validate-core` / `package-local`。已补回文案，不改执行代码或放宽测试；
  [直接读取该 UI 文件的 2 项合同测试](../build/generic-entrypoint.GV6VIE/skill-final.log)
  全通过。修复后未重跑整套；不把原失败日志改称全量 PASS。
- [核心验证](../build/generic-entrypoint.GV6VIE/core.json) PASS：41 能力、26 selectors；
  规范校验 PASS（101 文件），Skill 引用校验 PASS（4 references），skill-creator
  quick validation PASS。其 PyYAML 只安装在本轮独立开发验证环境，不改全局 Python。
- 额外真实离线沙箱预检：外层沙箱最初拒绝嵌套；经正常宿主权限启动后，过窄的
  Python 安装读取范围仍导致 execvp 拒绝。显式绑定 Homebrew 安装树只读后，
  [同一临时读写测试通过](../build/generic-entrypoint.GV6VIE/native-local-probe-homebrew.log)。
  内层沙箱/断网不变，未调用模型。此单项不关闭全部 17 个 opt-in 跳过项。
- 用户选定 PRD 为代表性案例，先做 M1。完整材料、语义接入报告、7 项 M1 需求、
  两个依赖任务、独立行为检查、真实 SQLite/文件场景及预算范围仅保存于忽略的
  私有工程目录；不进入发行物。9 项检查器自测通过，不算模型或 M1 实测。
  对照原文修正了一处“确认集合变化应退回选择”的合同偏差，原 PRD 未修改。
- 当前控制流只持久化了提案/来源/准备事件，**无批准、无 attempt，目标根仍不存在**。
  真实执行停在一次具体范围批准门；不需用户复制 Hash、冻结口令或逐包授权。
  下游缺陷触发已验收上游自动失效重建仍未实现；完整 W1–W7 / M1–M4 不提前关闭。
  没有真实模型调用、目标安装、Git 提交/推送或发布。

### M1 实际启动 — 批准已记录，初始化失败未闭合（2026-09-18）

- 后续真实用户“批准”通过公开宿主入口记录；控制流从 revision 7 推进至 18。
  `advance-build` 创建了批准的目标/任务空目录，但未产出目标文件。
- 三次首任务尝试均在 Codex 加载 AGENTS.md 时遭到权限拒绝：无 JSONL 事件、
  thread ID、usage 或模型生成证据。独立业务检查、LOCAL 后继与 M1 验收均未运行。
  实际停止为 `TASK_REPAIR_BUDGET_EXHAUSTED`，不能沿用此前“无 attempt”的准备状态。
- 新暴露的通用缺口：本地进程预检没有覆盖真实 Codex 指令加载；控制器把
  `MODEL_PROCESS_FAILED` 统一标为可重试 REJECTED，重复派发相同初始化失败。
  具体拒绝路径尚未确定，不能把候选路径推断写成已证实根因。
- 私有[实际执行诊断](../build/generic-entrypoint.GV6VIE/M1_EXECUTION_STOP.md)保留
  公开 Readback、三次捕获与待修项。本轮仅记录/执行批准范围并诊断，没有实现修复、
  重置预算、扩大权限或通过新 Program 绕过尝试上限。修复后重新声明所需运行范围
  和追加预算；历史尝试保留，W7A/M1 继续未闭合。

### M1 暴露问题的生产修复 — 启动读取与失败重试（2026-09-18 至 19）

- `coding_process.py` 根据默认全局/项目指令发现链预检精确读取需求，准备时提供
  Readback、派发前再核对；没有把 `/usr/bin/true` 的沙箱成功当作会话初始化成功。
  `source_read_roots` 支持文件级绑定，不必为 AGENTS 文件开放整个父目录。
  仅显式指令文件可只读，认证/状态目录和写权限限制保留，不关闭 AGENTS 加载。
- `build_runtime.py` 把启动/接收器及明确不可重试的进程失败归为 BLOCKED，返回
  `HELD_COMMAND_FAILURE`；重启不重派，验证器启动失败也不会重复实施。
  旧的误分类 REJECTED 记录按任务最新结果只读解释，不改事件、不退还预算，
  不用更早的失败推翻后来的有效成功。实际产物缺失/检查
  失败仍可修复；模型完成不能替代本地 verifier PASS。
- 首轮 62 项定向通过（含兼容 coding runtime）；补齐的最终定向 57 项及
  Python 3.14 同组 57 项均通过。新增真实离线原生沙箱测试通过：精确指令文件可读，
  同目录模拟状态文件仍拒绝；使用正常宿主启动权限，内层沙箱/断网不变，无模型调用。
- 规范、Skill、核心校验 PASS（101 文件、4 references、41 capabilities / 26 selectors）。
  最终全量回归 827 项：809 通过、0 失败、18 条件跳过，812.984 秒；包含历史失败
  被后续成功替代后不误阻塞的回归。精确只读绑定两个实际指令文件的离线探测亦 PASS，
  无模型调用或目标派发。结果见本轮[修复报告](../build/coding-startup-repair.NSPver/REPAIR_REPORT.md)。
- M1 只读核对仍为 stream revision 18 / 3 attempts；预检定位两个未覆盖的指令
  文件。未改需求/Plan/批准/预算，没有第四次尝试。真实会话与 M1 验收仍待所需
  精确读取范围及追加预算批准后验证；W7A/M1 不因源码修复提前闭合。

### 运行可靠性实施 — 源工程已推进，真实验收未关闭（2026-09-19）

授权：用户“执行修复”，执行 [R0–R5 方案](FOUNDRY_RUNTIME_RELIABILITY_WORKPACK_EXECUTION_v0_1.md)。
以下为源工程进度，不是新 M1 执行批准，也不覆盖本节之前的真实失败历史。

- **R0/R1：已实现并通过全量回归。** 先用长中文、9 MiB 多事件流、长 stderr
  三个失败子例固定复现，再将接收器改为双流持续排空、原始字节增量 JSONL 与有界展示
  分离。默认单事件 8 MiB、双流总量 128 MiB；超限/写入失败仍不能完成，未新增 Hash 链。
- **R2：部分完成。** 模型上下文直接带 scope.executables 的明确工具路径；包清单
  包含 Generic Build CLI、Runtime、Source intake 文档。真实模型内的子命令环境、
  所有发行指令/引用资源闭合尚未证明，不能以 prompt 中的路径代替运行证据。
- **R3：主要恢复切片已实现，未全部关闭。** 同一控制库记录命令计划/启动/观测，
  目标写域之外保存耐久字节附件；丢失控制观测可由完整宿主附件恢复；部分 Case 只续跑
  未派发的检查，已知启动/验证器失败不在崩溃后误变永久未知。正常业务断言与 verifier
  基础设施失败分流。声明输出变化按依赖图失效/重建相关分支，保留无关文件、历史及预算。
  read-build 提供原始命令结果、阶段、附件/PID 诊断及下一动作。旧未知可记录真实用户
  的明确处置，但不能造假旧终态、验收旧输出、重置预算或通过新 scope 绕过未决效果。
- **R3 剩余边界：** PID 探测不等于可靠身份核对；启动原子性空窗、任意环境失败的
  自动复测/恢复、主动取消、涉及已覆盖历史版本的重建尚未闭合。这些明确保留为义务，
  不靠新增人工按钮宣称完全自主恢复，也不把保守停止称为缺陷已修复。
- **R4：离线真实通道验证已做；后续获批 M1 正在运行，尚未验收。** 外层受限环境最初拒绝嵌套
  sandbox_apply；正常宿主权限下保留内层沙箱/断网，19 项 local_process 测试全通过，
  包括 9 项真实原生测试：实际读写/解释器身份、超时与正常结束后的进程组清理、
  有界输出、精确只读指令文件、隔离与已观测结果恢复。这组离线测试没有模型调用。
- **R5：未关闭。** 已补公开文档的包资源，不代表专项退役、干净包 A/B 实际建设、
  新 Codex 会话加载所建 Harness 或发行完成。

证据（本地忽略目录，不进入发行包）：

- [采集旧实现失败](../build/runtime-reliability.8iBiEf/r0-red.log)，
  [部分检查/诊断旧失败](../build/runtime-reliability.8iBiEf/r3-red.log)，
  [已知失败故障窗旧失败](../build/runtime-reliability.8iBiEf/r3-failure-window-red.log)，
  [依赖失效旧失败](../build/runtime-reliability.8iBiEf/r3-dependency-red.log)。
- [113 项定向测试](../build/runtime-reliability.8iBiEf/engineering-focused.log)：104 通过、9 条件跳过；
  [最终恢复切片 62 项](../build/runtime-reliability.8iBiEf/r3-final-focused.log)全通过。
- [原生离线测试](../build/runtime-reliability.8iBiEf/native-local-host.log)：19 项全通过；
  [外层拒绝记录](../build/runtime-reliability.8iBiEf/native-local.log)保留，不改称通过。
- [最终核心](../build/runtime-reliability.8iBiEf/core-final.json)、[规范](../build/runtime-reliability.8iBiEf/spec-final.json)、
  [Skill](../build/runtime-reliability.8iBiEf/skill-final.log)均 PASS（41 能力 / 26 selectors、101 规范文件、4 引用）。
  [最终全量回归](../build/runtime-reliability.8iBiEf/full-final.log)：849 项，831 通过、18 条件跳过、
  0 失败，811.565 秒；此前第一轮全量同为 849 项 / 18 跳过 / 无失败。
  本次未修改 Skill/AGENTS、发布版本、提交/推送 Git。

本轮开始时公开只读核对真实 M1：revision 23，三条历史 REJECTED 和一条 UNKNOWN_SIDE_EFFECT；
`writes_performed=false`、`harness_e2e_verified=false`。旧采集尾部不能由新代码补造；
现有 M1 verifier 未带新 ASSERTION 分类字段，失败时将按未分类基础设施路径停止，
不能在已批准绑定背后修改其字节。

用户后续回复“允许处置并按原范围继续 M1”，宿主读取真实 task/turn 引用后经公开
resolve-build-attempt 记录处置（revision 24），旧 UNKNOWN 历史保留，未接受旧输出、
未重置预算。随后原 scope 内 advance-build 启动，当前观测 revision 27 / IMPLEMENT-LIBRARY
在途；真实结果待记录。本次不另建或授权新的探针范围。

#### 后续入口修订与真实停止（2026-09-19；覆盖上文“在途”快照）

- 用户改为“PRD＋开发需求 → 开发文档 → 人工 Review → Foundry”。旧 PRD 直入链路不再继续。
  已更新计划、Workpack 归属、AGENTS 和公开接口政策；[新合同](GENERIC_BUILD_PLAN.md#搭建文档与人工-review-统一入口2026-09-19)
  标明 `PROGRAMMATIC_GATE_NOT_IMPLEMENTED`，不把文档更新当成程序门禁完成。
- 停止核对时模型进程仍在途；首次撤销的 revision 27 已过时，公开 CLI 正确返回 CAS 冲突，
  没有覆盖运行观测。再读状态确认进程已退出：完整模型终态已观测，首个独立检查拒绝，
  `HARNESS_RUN.md lacks a command example for --pure`。检查器缺少新 ASSERTION 分类字段，
  按约定停为 BLOCKED，而非擅自修订/放宽检查器；LOCAL 后继与验收均未发生。
- 随后通过公开撤销入口成功记录，revision 34，原 scope 为 REVOKED。旧 UNKNOWN、用户处置、
  新命令观测及失败全部保留，无预算重置、无已验收任务、无目标文件删除。
  这一旧路线结果不作为新流程的 M1 或 Harness 完成证明。
- 源码回归仍为本节已列的 849 项结果；本次后续仅变更输入政策/计划和真实撤销状态，
  未为新门禁修改生产实现。下一步先完成门禁工程与开发文档准备，人工 Review 后再准备新的 Foundry 范围。

#### 统一搭建文档入口（2026-09-19；扩展上述 PRD 专用政策）

- 用户将要求扩展到所有 Harness 需求：保留问答，先输出可访问、版本化的搭建文档，用户
  Review 并明确确认后才进入 Foundry。即使没有问题或后台 PASS，也必须交付文档并等待。
- 已同步 AGENTS、repo-local Skill/提示配置、兼容路由和委托说明、公开接口政策及 W1B/W5A/W6
  工作包要求。旧委托不能替代这一步；历史批准不重写，不追认旧 M1。
- 状态为 `POLICY_AND_SKILL_UPDATED / PROGRAMMATIC_GATE_NOT_IMPLEMENTED`。本次未修改生产
  Python，也未新增或恢复任何目标执行授权。不得以旧源码回归结果或本次指令静态校验声称
  程序门禁已实现；W5A 仍需正常确认与拒绝直入/自批/内容变化/跨路由绕过的配对行为回归。
- 普通核心诊断、源码工程和只读历史检查不增加这一步；实际文档确认及运行批准之后，
  范围内实施/验证/修复仍自动推进，无逐 Workpack 人工审批。
- 本次验证：`verify-spec` PASS（101 文件）、仓库 `validate_skill.py` PASS（5 引用）；
  `test_skill_contract.py` 2 项和 `test_portable_local_cli.py` 9 项全通过，后者包含临时包
  迁移启动检查；未运行目标 Harness。`git diff --check` 通过。
  skill-creator 附加 `quick_validate.py` 因可用 Python 缺少 PyYAML 未运行成功，未安装依赖。
  本次仅改指令/文档，未重跑全量源码套件；上述通过均不是新程序门禁的行为验收。

#### 新 M1 上游文档准备（2026-09-19）

- 用户请求“继续新的 m1 test”。按统一入口，已生成私人
  M1 搭建文档 v0.1（私人材料，不随仓库公开），状态
  `DRAFT_AWAITING_HUMAN_REVIEW / TARGET_NOT_RUN`，不将“继续”解释为对尚未展示文档的批准。
- 保留原 PRD 的本地翻译库子范围，提议明确分开“搭建 Harness → 新 Codex 会话实际使用
  Harness 开发 → 本地持久化场景与独立检查”。这仍是待 Review 的安排，不是已创建的任务。
- 本轮已复核原 PRD 大小、UTF-8 可读取和所选正文/全局边界；未宣称全 PRD 语义审查、完整
  AC-020 或产品验收。文档列明未读附件限制、合成故障与实际修复的区别。
- 公开只读 `read-build` 再次得到旧 Program revision 34，最近范围 REVOKED，0 在途、0 验收；
  更早的批准和未知结果处置保留，不向新流程继承。未修改旧控制库、检查器或目标产物。
- 新建议目标路径不存在且未创建。仅落成上游文档；文档人工 Review、程序门禁实现、独立
  检查准备和精确运行范围批准仍在前，未调用模型或执行目标测试。

#### M1 文档确认与程序门禁（2026-09-19）

- 用户真实消息“确认 M1 搭建文档 v0.1”已由宿主绑定展示/确认 turn，记入新通用提案事件；
  不是运行批准。原文保持不变，草案状态行保留其展示时含义；现状从控制事件读取。
- 共享 `build_review.py` 检查完整正文与真实消息引用形状，无额外 Hash、令牌或状态数据库。
  通用提案在创建控制库前拒绝缺 Review，来源捕获核对 source_id/路径/全文；准备、批准及
  推进重核 Review。兼容 CREATE/authoring 同样检查，委托不能代替人类 Review；真实人类
  REOPEN 可附新 Review，历史可读，撤销不被陈旧文档阻断。消息真实性与语义映射仍由宿主核对。
- 新 `test_build_review.py` 14 项配对行为测试通过，覆盖五类来源直入、代理自批、相同确认换绑、
  内容变更、跨路由/委托、历史只读与新确认正常接入。临时样例批准不能用于用户工程。
- 新私人 Case 材料在 `authoring_inputs/m1-build-review-v0.1/lab/`；独立检查器自测 8 项通过。
  补入共享工作稿引用保护，移除固定英文命令正则作为使用质量判据；使用质量仍须真实观测，
  并未因此宣称通过。检查器故障不输出业务 ASSERTION。旧 M1 文件、检查器、预算和历史未改。
- 新 Program `FOUNDRY-M1-REVIEWED-BUILD-20260919`，独立 revision 控制库，revision 4：
  文档确认/ABC 提案、5 个完整来源、未批准范围。无 attempt、目标不存在、未调用模型。
  当时的准备事件将完整 Requirement/Plan 与权限投影到私人 M1 执行范围文档；事件身份及
  批准材料仅保留在本地控制记录中。不继承旧 M1 授权。
- 首轮全量 863 项、18 项 opt-in skip，出现 2 failure / 1 error：新增测试辅助模块使用裸导入，
  目录发现可运行而官方完整模块名选择器不能导入。已修为 `tests.build_review_fixture`；
  定向通用回归 80 项与官方 core 相关 7 项复验通过。第二轮全量 863 项、748.174 秒，
  `OK (skipped=18)`：845 通过，18 项按 opt-in 配置跳过；跳过项不是实际验收。
  套件仍出现 SQLite 连接清理 ResourceWarning，保留为诊断，不宣称零警告。
- 准备期间补充目标 JSON 字段错误的明确 ASSERTION 分类，不捕获全部验证器错误；8 项自测包含
  缺依赖仍报基础设施故障的反例。当前未批准范围重绑定检查器，权限/预算未扩大；旧准备事件
  留作历史，不用于本次批准。未修改已批准运行的验证器。
- `verify-spec` PASS（101 文件），仓库 `validate_skill.py` PASS（5 引用），`git diff --check` PASS。
  skill-creator 附加 quick_validate 仍因未安装 PyYAML 不可运行；未为它新增依赖。
- M1/W7 未闭合。结构接口检查不等于实际加载；真实模型使用、修复、重入、说明可用性须另以
  实际宿主/目标观测核对，未观测不算通过。本次止于新的运行范围批准前。

#### M1 二级执行器绑定修复与原生依赖预检（2026-09-19）

- 实际 M1 A 生成产物后，独立检查器使用 Python 自报别名启动子进程遭拒；控制器正确停在
  HELD_COMMAND_FAILURE / revision 15，A 未 ACCEPTED，B/C 未启动。失败历史及原检查器不改。
- 通用 `executable://NAME` 参数传递同一 scope 的原始程序绑定；准备及重规划拒绝未知引用，
  保留 venv 语义、不扩权限。新版私人检查器显式使用绑定程序，子进程崩溃不伪装业务断言。
- 同等原生预检提前发现 SQLite 动态库读取缺口；在明确的诊断依赖下验证二级启动、15 步合成
  观察、SQLite 重开和零写限制。新增依赖未授予实际 M1；普通单测或 true 探测不等于运行准备完成。
- 通用控制器 50 项、私人自测 9 项、新原生预检 4 项、本地接收器原生组 20 项通过。
  全量 868 项 / 764.169 秒，849 通过、19 opt-in skip；verify-spec 与 validate_skill 通过。
- 本轮只做源码工程和临时离线回归，无模型、M1 新尝试、预算重置、安装或发布。
  恢复需展示新版检查器、子进程参数及实际依赖的新运行绑定；M1/W7 仍未闭合。
  详细证据保留在本地私人 M1 修复报告 v0.2 中，不随仓库公开。

Status: `CORE_PRODUCT_IMPLEMENTED_VALIDATED_AND_PORTABLE`

Active delivery profile: `SELF_USE_LOCAL_TRUSTED_OPERATOR`

The active tracker covers the local Foundry engineering product. Candidate generation and sibling Runtime construction are optional compatibility extensions, not core completion gates. The superseded Epoch 9 tracker is preserved in [`archive/V2_9_IMPLEMENTATION_TRACKER_EPOCH9_ARCHIVE.md`](archive/V2_9_IMPLEMENTATION_TRACKER_EPOCH9_ARCHIVE.md).

| Delivery tier | Scope | State | Completion evidence |
|---|---|---|---|
| `CORE_IMPLEMENTATION` | Product identity and CLI | `COMPLETE` | `version` and machine-readable product identity |
| `CORE_IMPLEMENTATION` | Requirement/Architecture readback, locks and compile | `COMPLETE` | Explicit Hash-bound dual lock and read-only compiled contract |
| `CORE_IMPLEMENTATION` | Profile graph, rule evaluator and generic transition engine | `COMPLETE` | Data-driven topology with one shared engine |
| `CORE_IMPLEMENTATION` | Authoring and bounded runtime advance | `COMPLETE` | Typed real-gate stops, parent-scope narrowing and idempotency |
| `CORE_IMPLEMENTATION` | Checkpoint, Resume and Explain Stop | `COMPLETE` | Durable event-bound recovery without replaying committed effects |
| `CORE_IMPLEMENTATION` | Portable local package and startup | `COMPLETE` | Logical roots, containment, dependency discovery and diagnostic self-check |
| `POST_IMPLEMENTATION_VALIDATION` | Core behavior and evidence projection | `COMPLETE` | 41 behavior-bound capabilities, 17 failure paths, 26 exact selectors, 278-test regression, deterministic evidence projection |
| `OPTIONAL_COMPATIBILITY` | Candidate generation and local release-ready gate | `IMPLEMENTED_NONDEFAULT_NOT_RUN` | Preserved implementation; excluded from default route and core validation |
| `OPTIONAL_COMPATIBILITY` | Control registration, Driver verification and Workpack Runtime | `IMPLEMENTED_NONDEFAULT_NOT_RUN` | Preserved implementation; no Execution Root, A3, Driver or Workpack required for core completion |
| `OPTIONAL_COMPATIBILITY` | Main execution package structural validation | `IMPLEMENTED_NONDEFAULT_NOT_RUN` | Preserved implementation; nonblocking for local Foundry delivery |
| `OPTIONAL_SECURITY_HARDENING` | External Trust Anchor, independent certification and dynamic adversarial work | `NOT_RUN_NOT_REQUIRED` | External certification remains false |

## Active completion rule

Foundry v2.9 core is complete when all of the following are true:

1. The 41 declared core capabilities bind to real modules, public entrypoints and exact tests.
2. Official core validation passes without creating Candidate or Execution roots.
3. A temporary relocated local package passes version and diagnostic startup smoke.
4. External certification remains false and optional security hardening remains `NOT_RUN`.

## Non-goals for core closure

- No Requirement reopen, Candidate generation, Human Gate or Runtime Bind.
- No Execution Root, A3, Program Driver or Workpack execution.
- No dynamic adversarial reproduction or optional security hardening.
- No target installation, publication or external certification claim.

## Slice 15 completion evidence

- Official core validation: `PASS`; SHA-256 `ddc49e3985dd54ea975f8515cca45c1bad8fafe3f1431742ec6f870e2519bb55`.
- Product Manifest: SHA-256 `f09488e536b1d060b0e77a0dffbdae34e53d05e14d5c39883ce7df74c40ac842`.
- Core evidence projection: `PASS`; SHA-256 `ce6ec07d7a518307dadf8279ca91ef2681a1384702779d0488e508fc06ea862b`.
- Full local regression: `278 tests`, `OK`; `PYTHONWARNINGS=always::ResourceWarning` reported zero resource warnings.
- Relocated local package: `47 files`; version and diagnostic startup smoke `PASS`; network and editable install not used.
- Optional compatibility: 8 capabilities preserved, `NOT_RUN`, `default_route=false`, `core_release_blocking=false`.
- Slice 15A test hygiene: three test-only SQLite connections now close explicitly; the exact two-test warning regression passed without changing production code, capability counts, validation scope, validation SHA or evidence-projection SHA.
