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

## Generic upgrade execution — 2026-09-18

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
