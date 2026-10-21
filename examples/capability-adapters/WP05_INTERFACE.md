# WP05 观察与展示组件：实际接口与后续适配

状态：2026-10-18，WP05 公共包 [local-dashboard@1](packages/local-dashboard/1/guide.md)、WP06 明确 Program/prepared 的 Foundry 只读适配及 WP08 目标原记录适配均已实现。公共 Observer、快照/SSE、步骤和响应式侧栏/PiP 保持共用；WP08 工程取证、本轮实际浏览器状态和未验边界见 实施记录（本地历史记录，不随源码提交）。真实新任务界面、完整 D0–D4/F/H 及效果验收不能由工程夹具关闭。协议保持 2.9、Plan 保持 1.2；本接口不新增权威事件、业务调度或通用门禁。

本次 WP08 两点最小修复见修复记录（本地历史记录，不随源码提交）；下列初次工程实施记录保留为历史，新测试及实际浏览器结果以修复记录为准。

依据现行 Workpack 执行计划第 3、4 节及三份看板 V0.5。版本和环境准备继续复用 WP01/02，WP05 提供公共观察接口，Foundry 事实接入归 WP06，目标自身事实接入归 WP08。它不改变既有验收编号或进度分母。

此前步骤与响应式实现及验证见实施记录（本地历史记录，不随源码提交）；以下步骤字段属于可选显示投影，既有未提供步骤的来源继续可用，不修改协议 2.9 的权威记录。

此前步骤与布局阶段，本机 Chrome 已实测工程夹具的原生 PiP、紧凑布局、调整尺寸及主页面在后台时的步骤更新；窄侧栏已用浏览器 320×640 视口实测。当时 IAB 仍出现打开后立即关闭，不能据此归为所有宿主不支持。完整 D0/D1/D2/D3、真实新任务及效果验收仍未关闭；本轮 WP08 浏览器状态单独记录。

## 1. 从明确版本与本机绑定进入

调用方先选择能力包的明确版本、包位置和入口。公共组件版本、目标交付版本、当前业务记录版本分别保留；换公共组件不会改写旧任务归属。版本资料沿准备器的既有来源映射，实际加载入口仍须与选定包对应，不以填写一个版本字符串代替核对实际消费内容。

WP02 的 `environment.resolve_environment()` 负责解析所选依赖的本机位置。其输入为 `requirements`、`bindings` 和明确的 `project_root`；需求使用 `id`、`kind`（`executable`、`directory` 或 `file`），按需声明 `version_min`、`version_max_exclusive`；绑定提供 `path`，已有版本观察可填 `observed_version`。输出包含带 `resolved_path` 的绑定、`scope_fragment`、诊断和状态。最终字段以该模块实现与说明为准。

```python
# 接口调用示意；不是已经运行的宿主准备或版本探测。
from environment import resolve_environment

requirements = [
    {"id": "python", "kind": "executable", "version_min": "3.11"},
    {"id": "run_records", "kind": "directory"},
]
bindings = {
    "python": {"path": "/selected/python", "observed_version": "3.11.9"},
    "run_records": {"path": "runs/task-001"},
}
environment = resolve_environment(requirements, bindings, project_root="/selected/project")
# 宿主启动入口消费解析后的路径和诊断；此处仅示意环境解析，不启动服务。
```

这一步不安装、不搜索整机、不执行版本命令、不连接浏览器，也不启动业务。`observed_version` 是调用方提供的事实，不证明运行时探测已经发生。缺失或不符合的依赖只影响需要该依赖的组件；普通业务和未选择看板的项目继续原路径。纯解析不产生 attempt；以后真实探测沿原宿主或 Program 权限记录实际消耗。

`scope_fragment.executables` 和 `source_read_roots` 是准备材料，不是授权，可以按已选任务需要用于准备既有 request/scope。观察宿主可以消费本机绑定；看板接入不自动改动已授权的业务 scope、增加业务网络权限或让单次验收承担长期观察服务。端口、已选记录位置及浏览器入口由宿主配置承载；它们不因此成为新的能力类型。解释器或浏览器路径可解析，不等于实际服务连接或 Document Picture-in-Picture 可用。

启动入口使用 `scope_fragment.executables` 中保留的调用路径（或绑定中的 `absolute_path`），不擅自改用 `resolved_path`；后者仅记录实际对象位置，直接替换可能丢失 `.venv` 的解释器语义。环境状态为 READY/INCOMPLETE，诊断级别为 ERROR/INFO，READY 仍仅表示材料可准备。

## 2. 一份展示模型，保留不同事实的归属

公共部分只认识适配后的显示事实。以下划分用于现有组件与后续适配避免混用，不要求所有目标都填充相同字段或安装 Foundry：

| 部分 | 内容与来源 | 更新方式 |
|---|---|---|
| 身份与所选范围 | 运行类型、项目、交付版本、运行身份；Foundry 额外绑定 Program/prepared，目标绑定自己的任务范围 | 选择器与摘要显示已有范围身份，同项目/版本/run 的不同 prepared 可区分；缓存与订阅继续按完整选择隔离 |
| 组件版本 | 实际加载的公共组件和适配入口版本 | 随明确版本选择及该观察服务自身重启更新 |
| 业务快照 | 计划、成果、检查、待处理事项及原有预算，附来源引用与记录版本 | 由对应只读适配器提供，不从日志关键词重新判断接受 |
| 外部活动与时钟 | 输出活动、观察时间、耗时、到期等；未知项明确保留 | 可在业务记录版本不变时更新，不增加完成数或消耗 |
| 连接状态 | 当前视图是否连接、最近读取、传输缺口及最后可解释快照的新鲜度 | 由观察连接维护，不反向写业务状态 |

一个最小示意对象如下。名称与数值仅演示上述分工，不代表实际运行、授权、完成比例或新的固定预算；内部字段可随实际实现收敛。

```json
{
  "selection": {
    "kind": "foundry_build",
    "project_id": "example-project",
    "project_version": "candidate-2",
    "run_id": "example-program",
    "program_id": "example-program",
    "prepared_event_id": "example-prepared"
  },
  "component": {"id": "local-dashboard", "version": "selected-version"},
  "business": {
    "source_revision": {"stream_revision": 42},
    "scope_ref": "example-prepared",
    "proposal_ref": "example-proposal",
    "items": [
      {"item_id": "EXPORT", "state": "ACCEPTED", "evidence_refs": ["example-attempt"]}
    ],
    "completion": null,
    "budget": {"attempts_consumed": 2, "attempts_remaining": 1},
    "pending": []
  },
  "observation": {
    "observed_at": "2026-10-17T09:00:00Z",
    "activity": {"last_output_at": null},
    "gaps": []
  },
  "transport": {"session_id": "observer-session-example", "sequence": 7},
  "connection": {"state": "connected", "last_received_at": "2026-10-17T09:00:00Z"}
}
```

`completion: null` 表示本示例没有提供可据以计算百分比的完整口径。真实实现沿原合同的成果与完成条件显示；尝试数、输出字节、心跳、进程存活不转换为完成率。同一成果的修复保持原成果身份，失效按原事实回退。`budget` 原样来自所选范围的已有投影，不累加多个授权中已经累计的数值。目标没有预算记录时可以省略，不补造 Foundry attempt。

上例是页面组合视图。实际 reader／显示文件只交接 selection、business 和 observation.activity/gaps；服务填写 component、observed_at 与 transport，connection 由当前页面维护，不从业务源接收。当前 completion 非空时使用 completed、total、label，具体字段沿组件 guide；原业务有更复杂口径时由对应适配器先形成一致的显示投影。

实际页面只得到必要且已脱敏的显示内容、可展示标识和证据引用；本机解析路径、完整环境变量、凭据及原始输出不因该示例而直接推送到网页。外来文本按文本渲染，证据访问沿原方式。

## 3. WP06 与 WP08 的最小接入职责

当前可用入口位于 `packages/local-dashboard/1/dashboard.py`。宿主可调用 `Observer({local_id: {"selection": selection, "reader": callable}})`，再用 `start()`、`url`、`stop()`/`wait()` 管理该观察实例；reader 只做及时返回的只读投影，不执行业务命令。也可运行包内 CLI：

```text
/选定/.venv/bin/python -I -B /选定/local-dashboard/1/dashboard.py --config /项目/dashboard.json
```

配置为 `{"runs":[{"id":"current","selection":{...},"source":"display/task-001.json"}]}`，只读取明确列出的显示 JSON，相对路径以配置文件目录为准；各 source 返回同一 selection 及 business/observation。完整示例与参数见 [guide](packages/local-dashboard/1/guide.md)。CLI 输出本实例 URL，宿主用 Ctrl-C/SIGTERM 或 Python `stop()` 关闭；没有业务执行、批准或任意文件浏览 API。端口、轮询和空闲退出可由宿主配置；不修改业务 scope 或预算。

同一实例的短暂断连由 EventSource 重新订阅完整快照。服务进程重启会产生新的会话和随机 URL 前缀，宿主重新打开本次启动输出的 URL；旧 URL 不自动指向新实例。组件升级也沿此路径，不要求业务重启。

| 接入点 | 提供什么 | 保持原有职责 |
|---|---|---|
| WP06 Foundry 适配 | `read_build_scope()`／`read_foundry_projection()` 提供明确 Program/prepared 的计划、来源、预算、有效接受及待复验状态；已有 readback 的恢复建议和证据 | 单次读取事件并复用原 `_scope_readback()` 和纯投影，不复制接受、计数、返修或恢复算法 |
| WP08 目标适配 | 已实现包内 `target.py`，读取明确声明的 DATA/DOC/host-review 原报告与关联文件；映射运行身份、范围、步骤和成果 | 当前为文件型接入，不依赖 Foundry 控制库、完整材料清单、搭建聊天或 Foundry 长期运行；其他目标可沿既有 Observer reader 接口接入 |
| WP05 已实现的共用展示 | 运行选择、状态布局、新鲜度、快照和连接传输 | 不提供批准、advance、返修登记、报告归并或业务命令 API |

### WP06 已实现的读取一致性与边界

当前 `read_build()` 先读 proposal，再读取事件列表，存在正常新增 proposal 使“旧顶层 proposal、新 stream_revision”并存的窗口。每个 authorization 的 prepared、plan、来源和预算则来自第二次同一事件列表，内部没有因此拼错。本次保留该原入口的双读语义；WP06 不消费其顶层“最新 proposal”作为选定范围的依据。

WP06 的 `read_build_scope(control_db, program_id, prepared_event_id)` 从单次事件读取取得明确 prepared 的成组字段，沿 `project_execution_state()` 等已有投影取得当前有效接受、合法复用及待复验。`read_foundry_projection(control_db, selection)` 映射为 WP05 的显示白名单，按当前有效接受计算本范围成果，不以历史最后一个 ACCEPTED 或仅本 prepared 的尝试历史替代当前接受。原预算沿 lineage 投影，仅展示一次；不在公共看板重写算法。

当前入口只显示配置明确选择的 prepared，不自动改选新授权；`authorization` 保留该 prepared 原 proposal 的授权基线。显示任务、`business.proposal_ref` 和完成率分母使用本 prepared 最近一次实际 `BUILD_ATTEMPT_STARTED` 绑定的 proposal；没有本 prepared 尝试时使用 prepared 原绑定。仅新增但尚未进入本范围尝试的 proposal 不自动切换画面。旧范围已被合法接续时显示历史及后续 prepared 引用。计划、来源、接受和预算来自同一事件列表，外部活动及自然到期在每次读取时更新。未新增控制写锁、业务事件或重放；浏览器连接不持有长期数据库读取事务。

源记录版本不变时仍可更新活动、连接和时间派生状态。`APPROVED` 只反映已读取的授权状态；现有派发时的新鲜度检查仍归控制器，观察组件不模拟派发或据此保证未来命令可执行。

### WP08 的独立使用交接

当前 [target.py](packages/local-dashboard/1/target.py) 随完整公共包交付；[目标说明](packages/local-dashboard/1/target-guide.md)提供选定包文件绑定、`--config` 启动、SIGTERM/Ctrl-C 关闭及原文件映射。独立启动只需所选包、项目显示配置、声明 Python 和目标原记录，私有独立预期可使用事先固定的摘要，不要求交付完整 prepare 材料或连接 Foundry。目标交付包含选定组件版本、实际启动／关闭入口、业务适配与显示配置、声明依赖和记录定位。新会话只拿这些交付内容及声明宿主即可使用；目标产生自己的运行身份，旧运行仍引用旧版本和证据。项目参数、业务标签及定制留在项目；公共组件只维护一处。没有过程记录时先展示可确认的结果及缺口，确有需要才在实际步骤边界补轻量记录，不把通知丢失变成业务失败或重调工具的理由。

## 4. 已实现的连接、生命周期及验收边界

单次来源读取形成业务快照后，侧栏与 PiP 共享同一运行的采集与缓存；第二个视图不再执行一遍完整 CLI。观察传输使用自己的会话及序号，不拿它冒充业务事件版本。首次订阅、重连和丢失序号时，以连接建立后的快照握手或等价方式避免快照与订阅之间遗漏。重复通知只替换对应状态；恢复显示不触发业务重放、报告恢复或控制写入。断连时保留最后可解释快照并标明新鲜度，不把它当成当前确认结果。

长期观察服务由查看它的宿主管理；原 command 的资源仍按原 `verification_resources` 收尾。专门验收看板的临时实例可以由测试命令拥有并清理。关闭一个视图只释放该订阅；无人使用时按实现选定的空闲策略退出自身服务，只释放自己拥有且不再共享使用的资源。业务进程、其他运行、SDK、定制和旧证据保留。升级后在观察服务自身重启时采用所选版本，不要求业务重启或热替换。

HTTP/SSE、单采集缓存、页面及关闭机制已有实现；每次 SSE 订阅都获得完整快照，慢客户端不形成业务背压。此前 IAB 已观察到侧栏 SSE 更新、断连/来源读取失败后的保留与恢复，以及 320/360 CSS 像素下无横向溢出。此前新增步骤与布局已在 Chrome 工程夹具实测原生 PiP、360×240 起始布局、窗口调整、主页面后台更新及 320×640 窄侧栏；IAB 仍打开后立即关闭，原因未定。两类看板完整范围、文字缩放及其他未测子项不能由这些局部结果或路径解析代替。宿主不支持 PiP 时保留侧栏和原业务。V9 第二设备与 PiP 分别记账。

范围显示补修只把已有 Program/prepared 身份呈现在选择项及侧栏／紧凑摘要，不改来源、缓存键、连接或控制职责；目标不因此需要 Foundry 字段。原 WP05 初次交付测试与浏览器证据保留为历史，新增结果另见 范围显示修复（本地历史记录，不随源码提交），该轮未关闭实际 PiP 或真实接入验收，此前步骤与布局阶段的 Chrome 夹具局部结果另记。

## 5. 原验收内的后续检查与当前边界

- F06：正常新增 proposal 的读取窗口、明确 prepared 隔离、有效接受／失效／复用投影、累计预算不重复相加；revision 不变时仍更新活动与到期。
- F06/F07：重复读取、重连和服务重启只恢复展示；观察器不产生控制写入。并发生产者的合法写入不误算为观察器写入。
- H01/H07：目标新会话及独立运行、多运行隔离、关闭一个视图不停止其他运行；H05 实际检查看板组件升级与项目定制保留。
- D0、F08/H09：真实 PiP／布局及功能、开销、理解效果分别取证；本接口文档不能关闭这些项。

这些沿用原场景，不新增全组合测试或普遍审批。WP05 公共组件和 WP06 Foundry 工程接入已有代码，WP06 初次复验已归档；WP08 目标适配工程已实现，真实新任务期间的界面、完整浏览器与效果验收仍按原项补证，不从代码或工程夹具推导整项通过。

## 6. WP06 Foundry 宿主实际入口

[foundry_dashboard.py](foundry_dashboard.py) 读取配置中明确列出的 Foundry 控制库，加载 [build_observation.py](../../src/harness_foundry_factory/build_observation.py) 的只读投影。先使用 WP01 的既有 prepare 输出选定 `local-dashboard` 版本、文件和 Python 绑定；宿主入口对材料调用 `consume.prepare_call(materials, "local-dashboard")` 核对后加载对应包的 `Observer`，不自动安装、更新或执行业务命令。宿主实际解释器须与材料中的调用路径相符，复用原父目录别名处理并保留虚拟环境语义；不自动换解释器或安装依赖。原始 `read_build_scope` 结果属于宿主，只将 `read_foundry_projection` 的显示字段交给浏览器。

```sh
/selected/.venv/bin/python -I -B /selected/Foundry/examples/capability-adapters/foundry_dashboard.py --config /selected/host/foundry-dashboard.json
```

```json
{
  "materials": "prepared-dashboard-materials.json",
  "runs": [{
    "id": "selected-build",
    "control_db": "records/control.sqlite3",
    "selection": {
      "kind": "foundry_build",
      "project_id": "DATA-TOOLS",
      "project_version": "交付版本未声明",
      "run_id": "selected-run",
      "program_id": "PROPOSED-DATA-TOOLS",
      "prepared_event_id": "selected-prepared-event"
    }
  }]
}
```

示例身份须替换为实际记录。`materials` 和 `control_db` 的相对路径相对于配置文件；材料内部仍沿 WP01 已解析的选版及绑定。`project_id` 必须与该 prepared 的 `requirement_ir.target.id` 一致；`project_version` 和 `run_id` 是宿主明确提供的显示标签，版本未知可写“交付版本未声明”，不能把 plan revision 当交付／已应用版本。不同 prepared 可使用相同项目、版本和 run，原完整选择隔离与选择器范围显示保持。

CLI 提供 `--port`（默认 0）、`--poll-seconds`（默认 1）、`--idle-seconds`（默认 300，0 表示不按空闲退出），输出本实例 URL、公共组件身份和观察会话。Ctrl-C/SIGTERM、空闲退出及 Python `stop()` 沿原 Observer 生命周期，仅清理自身资源。Python 宿主可用 `observer_from_config(config_path, **options)` 获得尚未启动的 Observer，再按原 API 启动和关闭。没有批准、advance、报告归并、任意文件浏览或命令入口。

恢复提示使用原动作、责任方及 Attempt 引用；普通清理警告保留诊断，不能变成新失败。页面只得到已有身份、证据 ID 和固定说明，不收到数据库路径、命令、原始来源正文、日志或凭据；显示身份本身也应使用适合展示的内容。未决观测保持待核对，读取不执行 `recover()` 或业务；接受百分比只说明所选计划的声明检查成果。候选范围通过不推导 apply；选定 apply 范围的原接受可照实显示，但不扩大为完整 Harness 业务验收。

WP06 初次工程复验及历史副本展示已完成，见 WP06 实施记录（本地历史记录，不随源码提交）。F 0/8、H 0/9、I/V 与原 R3 进度不变；真实新任务期间的界面、两类看板的 PiP／前后台完整范围、第二设备与性能仍未验收。

## 7. 步骤和两种布局的交接

公共显示投影接受可选 `business.steps`（数组）及 `business.current_step_id`。每个步骤使用唯一 `step_id` 和 `state`，并可提供 `label`、`detail` 和 `depends_on`；依赖仅表示源计划已有关系，不由页面生成执行顺序。没有步骤的旧来源继续使用原成果/当前状态展示，不要求目标 Harness 填写 Foundry 字段。`current_step_id` 可省略或为 null；非空时引用同一快照的步骤列表。

Foundry 使用实际采用的计划 Workpack 作为步骤身份和顺序，沿同一事件读取取得有效接受、失效、只复验及尝试状态。已记录的实施/检查阶段作为说明；未决启动不等于仍在正常运行，未知保留待核实。`business.current` 的授权说明与步骤展示分开；`completion`、原累计预算与恢复职责不变，不按步骤通知、阶段数或重连次数增加计数。

侧栏展开步骤、依赖、成果与详细记录；PiP 使用同一前端状态突出进度、当前步骤、可区分范围和异常，按窗口宽高压缩次要信息，完整身份和详情仍可在侧栏查看。视图类型与密度分别处理，不按宽度把窄侧栏误作 PiP；开启第二视图不新增采集器或 SSE。原生 PiP、缩放及前后台的实际完成范围见对应步骤与布局实施记录，不能由普通小窗口或截图推导全部通过。

## WP08 目标自身记录只读接入（2026-10-18）

[目标实际入口与配置](packages/local-dashboard/1/target-guide.md)随完整公共包交付，工程取证及本轮浏览器实际状态见 WP08 实施记录（本地历史记录，不随源码提交）。

`local-dashboard@1/target.py` 随选定公共包独立启动，读取目标显式选择的 DATA、DOC 和 host-review 原文件，不依赖 Foundry 控制库、完整材料清单或搭建聊天。DATA/host-review 在原检查读取中添加可选 `observation_binding`，DOC 复用原输入绑定、实际 CLI 导出及执行记录；私有独立预期可引用事先固定的摘要。HOST 通过显示前核对 task/snapshot 声明的完整依赖集合；报告缺失、截断或可解析但不完整时按单项显示来源缺口，其他可解释成果继续更新；同一声明范围内该项已知 FAIL/ERROR/INVALIDATED 保留原状态与原证据引用，首次缺口保持未知，旧 PASS 不借缺口继续算完成。连接与恢复显示不执行检查、报告恢复或业务命令，也不改变预算。

WP08 初次取证区分 DATA/DOC 新工程输入的实际 CLI 与独立检查记录、PRD 的合成宿主观察及真实目标业务验收；本次补修范围见后节。共享 UI、步骤、缓存和响应式组件未重做；组件升级、冲突和移除沿原 merge/apply 工程交接。测试数量、跳过原因及本轮实际浏览器状态统一见实施记录；此前 Chrome 证据不代替本轮目标接入复验。真实新任务、PRD 语义/视觉、第二设备、完整 H01–H09 和性能/理解效果仍待验收。

进度保持：能力最小代码 **4/4（100%）**、全量代码 **4/6（66.7%）**、V **0/12**、能力子计划 **4/18（22.2%）**，F **0/8**、H **0/9**；D3 工程接入已实现但整阶段未关闭，原 R3 原范围 **100%** 不变。不新增分母。

后续衔接 WP09 固定候选及接收设备准备、WP10 对照，并在原定新任务补齐业务与实际画面证据；D3 仍按 H01–H09 原标准收尾，不用工程通过替代真实验收。旧产物和证据保留，协议 2.9、G1/G2 与发布边界不变。

## WP08 单项来源与绑定补修（2026-10-18）

本次最小修复隔离单项报告缺口，其他已知成果和步骤继续显示；原检查尚未读取的 `null` 或缺失绑定不当作文件版本变化，明确的 FAIL/ERROR 与绑定缺口同时保留。只有已观察摘要与当前可读摘要确实不同才显示 INVALIDATED；PASS 仍要求全部必要绑定和原检查记录完整。单项失败缓存只在共享规范化成功后提交，保留的旧失败继续引用其原证据，不将新报告地址冒充旧失败证据。范围选择、只读职责、预算和恢复执行职责均不改变。

本次自动测试、47 项条件跳过逐项对照、实际侧栏/画中画操作与清理事实见修复记录（本地历史记录，不随源码提交）。新 DOC 负例是缺少 notes 时的原生 ASSERTION，不调用导出 CLI；不借用初次 DOC 导出或 Chrome 观察作为本次通过证据。

本次补修不增加验收分母或完成项：能力最小代码 **4/4（100%）**、全量代码 **4/6（66.7%）**、V **0/12**、能力子计划 **4/18（22.2%）**，F **0/8**、H **0/9**；原 R3 原范围 **100%** 不变。实际浏览器工程观察与真实新任务、第二设备及完整 F/H 验收分别记录；协议 2.9，G1/G2 与发布边界保持。
