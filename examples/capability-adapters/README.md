# 可选能力准备与接入

WP01/02 提供纯 Python 材料 API 和 CLI：显式选择外置资料或工具版本，解析本机依赖，输出当前 Generic 接口可用的片段。它们不创建 Program、不安装、不执行所选工具、不签发批准或接受，也不调整预算。原来的文档直接搭建仍可使用。

本目录保留资料与单文件工具小例，并已交付 [Qt/CMake@1](packages/qt-cmake/1/guide.md)、[DATA@1](packages/data-summary/1/guide.md) 及宿主消费核对入口。WP04 已补 [升级交接](UPGRADE.md) 与 `upgrade.py`，复用现有文件合并和原核心合法接续；WP05 已交付 [local-dashboard@1](packages/local-dashboard/1/guide.md) 公共观察服务与页面，实际调用见 [WP05 接口](WP05_INTERFACE.md)。当前工程测试支持 I1–I4 代码交付，不能关闭 V1–V12 的完整实际目标、升级、恢复或设备验收。

## 显式选择与调用

使用项目 `.venv/bin/python -B examples/capability-adapters/prepare.py --config /实际/config.json --output /新的材料目录`。不要将输出目录设为目标工作区；已有材料目录保留，不覆盖。

```json
{
  "project_root": "/明确的项目根",
  "selections": [
    {"directory": "/选定包/reference-notes/1", "version": "1", "workpack_ids": ["BUILD"]},
    {"directory": "/选定包/text-count/1", "version": "1", "workpack_ids": ["BUILD"]}
  ],
  "environment_bindings": {
    "python": {"path": "/实际/.venv/bin/python", "observed_version": "3.14.0"}
  }
}
```

路径和版本为填写示意，`observed_version` 必须换成已有真实工具观察；不把该字符串当成准备器已执行版本探测。`project_root` 明确且为绝对路径；相对包目录、相对本机文件从该根解析。可执行文件的裸命令名只沿 PATH 查找该项，`./tool` 明确指项目路径。输入可另带 `source_root` 和 `base_materials`（现有生成器输出的 JSON 对象）以合并已有 request/scope。

Python API：`build_materials(config, output_root)` 返回 `(materials, files)`，不写文件；`write_materials(config, output_root)` 只创建新的材料目录。CLI 返回 0 只表示材料准备 READY；INCOMPLETE 返回 1 并保留已生成的材料和具体缺项。引用或冲突错误在写出前报错。写出期间的 I/O 异常可能留下该次局部材料，应保留并改用新的结果位置；不会恢复或重跑任何业务命令。

## 包的最小约定

包根的 `capability.json` 是可选外置约定，不是协议 2.9／Plan 1.2 的新字段：

| 字段 | 含义 |
|---|---|
| `name`, `version`, `usage` | 明确名称、所选版本；usage 为 build/runtime/both，说明是否交付后仍需要 |
| `inputs`, `outputs` | 该能力适用的输入和输出说明，不代替项目合同 |
| `materials` | 相对普通 Markdown/text/JSON 文件，作为生产者可读来源 |
| `tools` | `id`、包内相对 `path`；脚本可声明 `interpreter` 及 `interpreter_args`，解释器由环境绑定提供；原生程序自身需可执行 |
| `runtime_files` | 工具实际使用的其他显式普通文件，不递归扫描，也不能代替材料或工具入口 |
| `environment` | 所选依赖列表：id、kind(executable/directory/file)、可选数字 version_min/version_max_exclusive |
| `verification_files` | 检查器专用相对文件；确为双方共享的原始输入或不含判定的公开运行依赖时用 `{"path":"input.csv","shared":true}`。独立预期不能标成共享以规避隔离 |
| `support` | 相关支持条件说明，不自动变成额外门禁 |

已有包管理器继续维护 SDK、库及安装。此薄入口只读取显式清单；不导入包模块，也不执行动态发现。相同环境依赖的兼容数字范围取交集，不兼容或同名入口冲突明确报出；不以后一包覆盖前一包。包内引用解析到其明确根内的普通文件；SDK/framework 链接在本机环境层解析，不复制整棵树。

## 输出如何交给现有 Foundry

1. `sources/` 只保存生产者材料与公开版本说明；`source_manifest` 使用其中的相对路径。原材料来源保存在 `source_origins`。合并 base 时保留原 source_id、原文及定位，增加选定任务的既有 `SOURCE` 输入，不改变项目目标、业务断言或预算。重新组合的 request 不继承先前 document_review 或运行调用上下文，按既有流程准备真实确认。
2. `scope_fragment` 提供已有 `executables` 和 `source_read_roots` 字段；`tool_bindings.*.argv_prefix` 的首项是可执行逻辑 ID，实际调用须沿既有工具解析。task 的 SOURCE 用于版本/生产依赖绑定，**不构成每任务的读取权限隔离**；当前来源快照和 scope 读取域会交给范围内生产者。
3. `preparation.verifier_inputs` 给出来源及 verifier 相对目标；`checker_files_fragment` 供既有受保护依赖入口使用。base 已有 verification_resources 时合并 checker_files，但不替调用方创建资源配置、检查命令或独立预期。宿主按映射保存到 verification_root，检查命令使用 `verifier://` 并真正从受保护副本读取。此时 `protected_copy_created:false`；真正的副本由原 Generic prepare 建立。完整选版的零选择分支也复用同一私有输入隔离、目标路径冲突检查、去重与合并，保留合法 shared 原始输入及无资源配置时的依赖片段。
4. `preparation.selections` 记录所选清单与显式文件身份。`check_selection(materials)`，或 CLI `--check-selection /材料/materials.json`，只读核对这些文件；MATCH 不代表业务接受、SDK 验证或文件锁。宿主交接入口 `consume.prepare_call` 已在消费前调用该核对，并从已匹配清单重建工具版本与调用前缀；不能仅换版本名后沿用旧接受。未声明 import/helper/动态库不属于此文件身份范围。

无 base 时只返回材料片段；有 base 时返回合并后的 request/scope，仍是 `MATERIALS_ONLY_NOT_APPROVED`。`preparation.changes` 列出相对 base 新增的来源、任务输入、工具绑定、读取根和检查依赖，供调用方审阅；不将它当成已应用的修改。宿主继续调用现有编译、来源捕获、文档确认、实际 Readback 和授权入口。准备器不接受项目结果、不调用恢复，也不自动创建目标。

已有准备结果也可作为 base，配合其 `source_root` 在新目录追加不同能力。旧 `selections`、`tool_bindings`、环境绑定与诊断一起保留，身份检查继续覆盖旧包；同名不同工具或已知版本观察矛盾仍报冲突。新能力可复用旧环境绑定；同一调用入口只重述路径且省略 `observed_version` 时，继续使用旧版本观察，避免重新制造版本未知诊断；显式 `null` 不用旧观察补充本次解析，仍按现有版本未知规则处理，不删除保留的历史观察。同一入口原来没有版本时可补充观察，数字尾零等价不误报冲突；矛盾观察和不同虚拟环境入口仍不能因此放行。`preparation.retained_diagnostics` 标明从 base 保留的诊断，因此旧 VERSION_UNKNOWN 信息与后来补充的版本可以同时存在。旧 ERROR/INCOMPLETE 不因追加一个 READY 包而清除；要重新核实旧缺项，修正原完整配置并输出新材料。追加不替换旧版本；更换版本、移除或重新核实旧缺项可用 WP04 的完整新配置入口，见 [升级说明](UPGRADE.md)。

普通工具与读取依赖按实际 `task_write_roots` 判断：工作区内的只读 `tools/` 或 `.venv/` 可以使用，不能与任一任务的写域重叠。调用路径本身、经过的父目录链接及实际对象均需保留该边界；工作区别名叠加写域内链接时，仍核对实际经过的可写入口，不能因最终指向外部而误放行。材料输出和私有检查器仍独立放置。合并可执行绑定时只消除等价父目录表述并保留已有调用路径，不把不同 `.venv/bin/python` 因指向同一二进制而合并。

固定工程包、五个独立能力候选与接收设备准备见 [候选分发说明](CANDIDATES.md)。打包不安装、不执行任务；当前V9采用本机干净环境实跑和环境差异测试，新用户/macOS虚拟机按需可选，不要求第二设备。

## 环境与验收边界

`environment.resolve_environment(requirements, bindings, project_root=...)` 输出 READY/INCOMPLETE、每项原路径/绝对路径/真实路径、调用方报告的版本、局部诊断和 scope 片段。保留解释器最终别名用于调用，避免 `.venv` 退化为系统 Python；`resolved_path` 另作事实记录。无版本约束且无报告时记 VERSION_UNKNOWN 信息，不阻挡材料准备；有范围但未知、预发布或厂商字符串无法作数字比较时明确未确认，不截断当正式版。修正绑定后可再次解析，无状态库或隐含缓存。

文件存在、范围匹配、SDK 链接可解析，都不证明实际接收器内能运行。纯解析 `probes_executed:false`，不虚构 attempt；后续实际探测沿原宿主/Program 记录消耗，修正环境后的 rebind、接受复用、只复验和恢复仍归原 controller。

此前覆盖材料准备、消费交接、两包定向测试与本机隔离 Qt 工程的真实 configure/build/CTest，以及两份 DATA 工程输入的实际 CLI 与独立检查。WP04 另补版本／目标文件／原控制接续工程验证，细节见 [升级说明](UPGRADE.md)。上述历史工程结果没有完成目标新会话、模型、新设备、PiP 或性能验收；当前 WP05 另有组件测试与部分 IAB 观察，范围见下节，不能替代这些后续项。

## 宿主实际消费与目标交付

`consume.prepare_call(materials, tool_id, args)` 是纯宿主 API：检查 READY、所有显式选定文件身份，从所选 `capability.json` 重建工具／版本／前缀，并核对具体可执行绑定仍对应准备时的调用路径及解析对象。返回 `local_argv` 和绝对 `argv`；不创建进程、Program、批准、预算或接受状态。CLI 仅输出同样的 JSON：

```text
python -B consume.py --materials /host/materials.json --tool qt-cmake -- configure --cmake executable://cmake --source /project/source-copy --build-dir /project/build --report-dir /project/reports/configure-1 --define CMAKE_PREFIX_PATH=/declared/qt-sdk
```

宿主在已有授权内紧接着将结果交给原执行者；不要把这个只读 CLI 当作真正执行。`executable://id` 使用已有逻辑绑定；`.venv/bin/python` 的末端链接保留。它不重新探测 SDK 版本，不形成文件锁，也不固定未声明的 import 或动态库；授权、受检产品绑定和接收器权限仍沿现有入口。

**完整材料与私有检查依赖只留在宿主。** `check_selection` 会读取独立判定文件来核对选定身份，生产者不能执行这一步，也不能因此得到私有读取根。目标交付只包含公开工具、显式运行依赖、项目自己的配置与声明的宿主环境，可直接运行工具，无需 Foundry 控制库或持续运行的准备器。项目独立预期另存保护域；交付清单按实际用途选择，不复制 SDK、整棵包目录或开发机 `.venv`。

Qt 包接受项目 source/build、配置、target、CMake 定义与测试选择；必测名称由项目独立预期提供。独立检查自行执行一次 CTest；普通 `test` 和独立检查若都选用，就是两次明确执行，不是恢复。CTest 会写 build/Testing，真实验收使用绑定受检产品的已批准可写副本／scratch，不能只开放 report-dir，也不能把旧 build 或生产者历史 XML 当作本次实际检查。

DATA 包仅处理明确的 CSV sum/count/ratio、单位换算、重复／缺失及舍入策略；具体口径由项目配置提供。完整独立预期与输入/config 身份一起核对，不导入生产算法。项目不适合这些方法时仍用原项目代码或其他工具，不强制把业务塞入此包。

两包检查器沿现有受保护副本及 `STRUCTURED_V1` 接口接入（具体参数见各包 guide）。包内不携带业务答案；独立预期由项目提供。Qt 必测名称仅核对覆盖，业务断言须来自项目可信测试源码或受保护外部测试，不能把同名恒成功测试当作业务验收。历史报告只解释或交由现有恢复入口处理，不触发本工具重新执行。 需要在成功清理后保留 Qt 原始报告时，可按 guide 配置：原始文件写入 `resource://report-staging/ctest`，与 `summary.json` 一起声明归档；使用其他合法新子目录时，同步声明对应附件。成功清理后从宿主附件路径取回，invocation 内原绝对路径仅作历史记录；不按旧路径重建资源或重跑检查器。此路径已补本地生命周期集成测试，仍不代表真实目标／接收器验收。

## WP07 非编码持续使用

[非编码接入](NONCODING.md)补齐 `doc-export@1` 和 `host-review@1`。DOC 工具读取项目的结构化内容与引用并实际导出；PRD、MARKET 保留项目自身生成工具，按声明工作流交给实际浏览器或检索宿主。快照与检查只处理声明文件和独立观察，不自动获得聊天工具或认证自报 PASS。

WP07 工程子集完成情况及测试见 WP07 记录（本地历史记录，不随源码提交）。真实 DOC 新材料、PRD 新变体、MARKET 新问题及实际宿主调用未验收，I5 暂不计为整项完成；其余进度与原 R3 保持不变。


## WP05 可选观察与展示

[local-dashboard@1](packages/local-dashboard/1/guide.md) 用现有 prepare/consume 选择包版本，交付包含 `capability.json`、`dashboard.py` 与 `web/` 的公开组件；项目记录位置、标签与适配配置独立保留。宿主通过 Python `Observer` 或显式 JSON 来源配置启动本机只读服务，侧栏和 PiP 共用一个运行的缓存与连接，不执行业务命令或接受、恢复。

WP05 实施记录（本地历史记录，不随源码提交）区分工程测试、完整回归及实际浏览器观察。IAB 侧栏与工程夹具 SSE 更新不等于真实 Foundry/目标适配，该轮 PiP 点击后关闭不算稳定 PiP 通过。WP06 Foundry 接入见下节，WP08 工程接入见本文末尾；D0/D1 完整浏览器验证、真实新任务界面、F/H 与效果对照仍待完成。原 R3 和 I/V 计数不变。

## WP06 Foundry 只读接入

[foundry_dashboard.py](foundry_dashboard.py) 是 Foundry 宿主入口，接收 `--config`，按配置的 `materials` 读取 WP01 选版材料，通过 `consume.prepare_call()` 核对选定 `local-dashboard` 后加载其公共 Observer。`runs` 中每项提供 `id`、`control_db` 和完整 `foundry_build` selection；Program/prepared 必须明确，项目 ID 与该范围目标一致。项目版本是宿主显示标签，未知时明确写未声明，不由计划版本推导。

配置、命令与 Python 入口见 [WP05/WP06 实际接口](WP05_INTERFACE.md#6-wp06-foundry-宿主实际入口)。Foundry 内的 `read_build_scope()`／`read_foundry_projection()` 使用一次事件读取，复用有效接受、失效、合法接续、累计预算与恢复说明；WP06 初次接入未改公共组件，原控制器保持。读取、刷新和重连只展示，不派发、恢复报告或重放业务。

WP06 工程复验及历史副本展示已完成，见 WP06 实施记录（本地历史记录，不随源码提交）。此处 WP06 初次结果不关闭真实新任务界面、两类看板 PiP 完整范围、WP08 目标接入或性能验收；F 0/8、H 0/9，能力和原 R3 进度不变。

## 历史：步骤展示与响应式布局补齐

`local-dashboard@1` 的可选步骤投影与界面沿原 WP05/WP06 增量补齐：侧栏展开完整步骤和详情，PiP 突出同一状态中的进度、当前步骤、范围和异常；百分比仍沿原成果口径。接口见 [WP05 接口](WP05_INTERFACE.md)，本次定向/完整回归与实际浏览器观察见实施记录（本地历史记录，不随源码提交）。目标来源未提供步骤时保持原显示，不要求 Foundry 字段。

原 WP05/WP06 记录保留为历史；上述步骤与布局交付当时不关闭 WP08、真实新任务界面、完整 D0/D1 或 F/H 效果验收，也不更新分发清单或发布。能力最小 4/4（100%）、全量 4/6（66.7%）、V 0/12 与原 R3 进度保持。

该步骤与布局阶段，本机 Chrome 已实际观察工程夹具原生 PiP、窗口调整、后台步骤更新和窄侧栏；IAB 仍出现打开后立即关闭。局部结果已记录，但不替代完整 D0/D1/D2、真实新任务或目标运行验收。

## WP08 目标自身记录只读接入（2026-10-18）

[目标实际入口与配置](packages/local-dashboard/1/target-guide.md)随完整公共包交付，工程取证及本轮浏览器实际状态见 WP08 实施记录（本地历史记录，不随源码提交）。

`local-dashboard@1/target.py` 随选定公共包独立启动，读取目标显式选择的 DATA、DOC 和 host-review 原文件，不依赖 Foundry 控制库、完整材料清单或搭建聊天。DATA/host-review 在原检查读取中添加可选 `observation_binding`，DOC 复用原输入绑定、实际 CLI 导出及执行记录；私有独立预期可引用事先固定的摘要。HOST 通过显示前核对 task/snapshot 声明的完整依赖集合；报告缺失、截断或可解析但不完整时沿原来源缺口路径保留最后可解释快照和失败，首次读取则保持未知。连接与恢复显示不执行检查、报告恢复或业务命令，也不改变预算。

本轮取证区分 DATA/DOC 新工程输入的实际 CLI 与独立检查记录、PRD 的合成宿主观察及真实目标业务验收。共享 UI、步骤、缓存和响应式组件未重做；组件升级、冲突和移除沿原 merge/apply 工程交接。测试数量、跳过原因及本轮实际浏览器状态统一见实施记录；此前 Chrome 证据不代替本轮目标接入复验。真实新任务、PRD 语义/视觉、第二设备、完整 H01–H09 和性能/理解效果仍待验收。

进度保持：能力最小代码 **4/4（100%）**、全量代码 **4/6（66.7%）**、V **0/12**、能力子计划 **4/18（22.2%）**，F **0/8**、H **0/9**；D3 工程接入已实现但整阶段未关闭，原 R3 原范围 **100%** 不变。不新增分母。

后续衔接 WP09 固定候选及接收设备准备、WP10 对照，并在原定新任务补齐业务与实际画面证据；D3 仍按 H01–H09 原标准收尾，不用工程通过替代真实验收。旧产物和证据保留，协议 2.9、G1/G2 与发布边界不变。

## 可选技术栈环境包

新增 Qt/CMake@2 与 Python-environment@1，旧版本保留。`selection.environment_profile`、调用级绑定、公开交付、恢复及后续作者接口详见 [技术栈接入](STACK_ENVIRONMENT.md)。完整清单仍是宿主材料；保护checker与独立预期不能交给生产者。材料READY、工程测试、实际目标和发布验收分别记录。

### H05 可选主题接口（版本 2）

新增 [local-dashboard@2](packages/local-dashboard/2/guide.md)，在外部观察配置中选择 `system`、`light`、`dark`，未配置保持系统主题。目标入口与 Foundry 宿主入口传递同一偏好，侧栏/PiP 共用状态；旧 @1 保留，未配置主题时接口兼容。需要重新选择新版完整文件绑定，不静默替换已固定组件。工程验证与真实浏览器待验边界见 H05 实现记录（本地历史记录，不随源码提交）。

### 累计工作与步骤历史（版本 3）

[local-dashboard@3](packages/local-dashboard/3/guide.md) 将累计工作进度与当前有效接受分开显示，并展开实施、各项独立检查、接受结果及历史记录。累计单位为当前 prepared 所展示计划中的原 Workpack，加上每个已确认额外缺陷的修复根事件所影响的 Workpack；同一修复链的重试与 continuation 不增加总量。历史完成量保留，失效接受仍须修复或复验；流程步骤与历史记录不增加验收分母。此投影不汇总其他 prepared，也不改变调度和原预算。

Foundry 宿主仅对支持新字段的所选组件启用扩展投影，默认原始读取接口不变。目标 Harness 来源没有提供新字段时继续使用旧展示。旧 @1/@2 和现有安装不会自动升级；选择 @3 使用原 prepare/consume 与[升级交接](UPGRADE.md)，重新绑定新版完整文件，不覆盖固定旧包。

验证范围见[公开实现摘要](../../docs/V2_9_IMPLEMENTATION_TRACKER.md)。本地原始证据不随源码提交；旧部署未自动升级，未合并 main 或发布，原 R3 及既有验收分母不变。


## 内嵌与外置显示、通俗文案（版本 4）

[local-dashboard@4](packages/local-dashboard/4/guide.md) 保留 @1–3，新增同一观察服务的内嵌／外置地址。
Chat 可按用户要求在 Codex 浏览器面板或外置 Chrome 打开；内嵌页隐藏画中画和全屏，
外置页按实际能力显示“画中画／全屏”，替换原先只会关闭浮窗的“使用侧栏”。
不使用浏览器名称作可靠身份判断，原地址无提示时按接口支持处理。
长身份和原状态移入详情，进度、当前检查和待处理事项保持分开；不改变累计计数、接受、
恢复、权限或预算。旧部署须显式选用新版完整组件绑定，不自动改写旧固定包。
