# 静态能力说明与本地候选交付

本表随源码版本固定，由 `src/harness_foundry_factory/build_capabilities.py` 生成。它用于查阅接入位置和诊断已有边界，不是权限表、自动选型器或新的运行前置条件。未列出的需求仍可由项目实现；登记不表示已授权、环境已满足或验收已通过。协议保持 2.9。

运行 `python src/harness_foundry_factory/build_capabilities.py` 可查看包含工厂认识、工厂执行、目标交付和验收边界的 JSON；`--id` 只筛选已知描述，`--markdown` 输出下表。读取不导入工具 SDK、不初始化资源、不调用模型、不访问控制库。

| Capability | Inputs | Runtime modules | Dependencies | Known unsupported combinations |
|---|---|---|---|---|
| temporary-files | `verification_resources.profiles.<id>: writable_areas, report_files, retention` | build_resource_lifecycle, verification_resources, resource_observation | Declared LOCAL checker | Cross-command persistent sidecars |
| sqlite | `Use a database path under the declared resource scratch area` | verification_resources | temporary-files; Python sqlite3 or the selected SQLite tool | None declared here |
| local-service | `network={mode:LOCAL_SERVICE,tcp:LOOPBACK,unix_sockets:[resource://scratch/...]} (declare one or both selectors)` | resource_network, verification_resources, coding_process | temporary-files; Native Codex receiver | LOCAL_SERVICE and REMOTE_SERVICE in the same command; Cross-command sidecars |
| remote-http | `network={mode:REMOTE_SERVICE,allowed_hosts:[exact hostname or IP]}` | resource_network, coding_process | Native Codex network proxy | REMOTE_SERVICE and LOCAL_SERVICE in the same command; Direct arbitrary networking |
| test-credentials | `verification_resources.profiles.<id>.credentials={ALIAS:{ref:env:VARIABLE,purpose:...}}` | resource_credentials, resource_observation | Declared host credential source | Automatic injection into CODEX implementation or unrelated commands |
| product-copy | `verification_resources.profiles.<id>.product_copy={files:[relative input],writable_paths:[relative generated directory]}` | verification_resources, verification_snapshot, resource_observation | temporary-files; Declared product source files | Implicit whole-repository copy; Accepting a result after declared source inputs changed |
| composition-upgrade | `Ordinary composition, G/A/C/N inputs and explicit file apply descriptions` | build_entrypoint, build_runtime | examples/harness-composition-upgrade/helpers/merge.py; examples/harness-composition-upgrade/helpers/apply.py; examples/harness-composition-upgrade/helpers/file_states.py | Helper diagnostics as controller acceptance; Byte-comparison helper resolving semantic conflicts; Helper-level multi-file transactions |
| business-workflows | `Group manifest plus v1/v2 workflow, original inputs, independent expected values and host evidence` | build_entrypoint | examples/harness-composition-upgrade/integration/business_requests.py; examples/harness-composition-upgrade/verifier/check_business.py; Explicit host browser/search tools when required | Chat tools implicitly inherited by a CODEX subprocess; Fixed sources as proof of live retrieval |

以下 WP 阶段进展文字保留各自记录时点；其中“待验”“尚未入包”等表述不代表当前候选状态。当前交付范围以所选包清单为准，验收结论以对应实际证据为准。

新增可选的外置能力入口（主源码工作区 `examples/capability-adapters/README.md`）已完成 WP01–04：显式版本资料／工具、本机环境解析、Qt/CMake 与 DATA 两包，宿主交出命令前的身份核对，以及完整选版和原核心合法接续交接。它与上表静态目录分开，不导入 controller，不安装或自行派发。WP05 已在主源码交付可选公共观察组件 `local-dashboard@1`；目标升级已有隔离工程证据，真实新会话业务、目标升级、新设备及固定候选仍待后续。本入口尚未列入当前分发清单；主源码工作区状态记录为 `docs/FOUNDRY_CAPABILITY_WP04_RESULT_2026_10_17.md`，不属于当前包内文件。

已有需求与能力对应关系够用时直接复用，不在每次执行前重新扫描或分析。资源描述不会自动进入目标组成，业务工具登记也不会把第三方 SDK 加入工厂核心。具体参数、网络真实权限和恢复语义以 [Build CLI](GENERIC_BUILD_CLI.md) 为准；按原始需求做独立结果验证，发现缺口后局部补齐。

本地候选交付使用显式文件清单，包含 [两个机制和三组业务材料](../examples/harness-composition-upgrade/README.md) 的 helper、固定输入、工作流和独立检查器。打包不会扫描未知插件或把整个开发仓库带入。解包后的 import、CLI、材料生成和固定样例检查只能证明可携带依赖闭合；实际模型、原生沙箱、业务工具、恢复与性能对照仍按各自验收范围记录。

开发工作区工程 ZIP 可以固定并保留作本地测试。最终发行候选仍须从明确选定的 Git commit 使用 `devtools/package_committed_release.py` 组装；工作区 ZIP 不伪装成该发行来源，不更换已发布 v0.5.0 ZIP，不自动提交或发布。完整 S4 业务未运行的部分不因本地候选完成而变成通过。

WP07 另补主源码中的 `examples/capability-adapters/NONCODING.md`：DOC 的 structured notes 导出、PRD／MARKET 的实际宿主工作流及输入／成果／观察证据交接。它们是可选包和文件工具，不向核心添加业务引擎、第三执行器或接受权。工程交接已有测试，新任务的实际宿主调用仍待验收；I5 未计为完整完成，原 R3 不变。详见 主源码工作区记录 `docs/FOUNDRY_CAPABILITY_WP07_RESULT_2026_10_17.md`（不属于当前包内文件）。


WP05 的 `local-dashboard@1` 包含只读来源 API/CLI、本机快照/SSE、侧栏/PiP 及宿主生命周期；版本与运行文件复用上述外置接入方式，不加入核心静态目录或原业务控制链。实际测试及部分 IAB 工程夹具观察见 主源码工作区记录 `docs/FOUNDRY_CAPABILITY_WP05_RESULT_2026_10_17.md`（不属于当前包内文件）。WP06 Foundry 只读适配已在主源码实现，工程复验已完成；WP08 目标适配、D0/D1 完整浏览器验证、新任务期间的真实界面和效果对照未完成；未更新固定分发清单或生成发行候选，也未发布，原 R3 及 I/V/F/H 计数保持。

WP06 的主源码入口为 `examples/capability-adapters/foundry_dashboard.py`，读取宿主配置及 WP01 材料、经 `consume.prepare_call()` 核对选定公共组件，再调用 `src/harness_foundry_factory/build_observation.py` 的 `read_build_scope()`／`read_foundry_projection()`。Program/prepared 的计划、有效接受与原累计预算来自同一次事件读取；不修改原 `read_build()` 双读语义或核心控制器。调用说明在主源码 `examples/capability-adapters/WP05_INTERFACE.md`，工程记录为 `docs/FOUNDRY_CAPABILITY_WP06_RESULT_2026_10_17.md`。这些主源码入口与记录没有因此加入既有固定分发清单；不发布，不将历史记录展示或工程测试算成真实新任务界面、完整 PiP 或效果验收。

步骤与响应式补齐继续位于主源码的 `local-dashboard@1` 及 Foundry 只读适配：可选步骤、当前步骤与已有依赖和成果使用同一份快照，PiP 紧凑展示进度和当前步骤，侧栏展开详情；范围区分及异常提示保留。当前实施与实测边界记录在主源码 `docs/FOUNDRY_DASHBOARD_STEPS_RESPONSIVE_RESULT_2026_10_17.md`，不属于当前包内文件。本次不新增能力类型、控制器、分发项或验收分母；原 R3 进度、协议 2.9 与不发布边界不变。

本机 Chrome 已有本轮工程夹具原生 PiP、紧凑布局、后台更新与窄侧栏观察；IAB 本次打开后立即关闭的原因尚未确定。两类看板的完整 D0/D1/D2、真实新任务、目标独立接入及效果验收仍未关闭；不把工程夹具等同于真实业务验收。

可选的 `local-dashboard@2` 提供外部 `system/light/dark` 主题偏好并保留 @1，侧栏和 PiP 共享同一状态。按[能力接入说明](../examples/capability-adapters/README.md)显式选择新版完整文件绑定，组件及其使用指南随所选能力包单独交付，不静默替换已固定版本。本说明描述公开接口与职责，不包含本地实施记录，也不代表具体目标已验收或已经发布。

可选的 `local-dashboard@3`（使用指南 `guide.md` 随选定的独立能力包交付，不属于通用运行包）增加累计工作进度、实施与逐项独立检查步骤、可查看的历史记录。累计单位为当前 prepared 所展示计划中的原 Workpack，加上每个已确认额外缺陷的修复根事件所影响的 Workpack；同一修复链的重试与 continuation 不增加总量。当前有效接受仍独立显示，已完成历史不恢复失效接受；步骤和历史数量不加入验收分母。没有跨 prepared 汇总，也不改变调度或预算。

默认 `read_build_scope()`／`read_foundry_projection()` 原始接口保持；Foundry 宿主仅在选定支持新字段的组件时启用扩展投影。目标 Harness 来源未提供新字段时保留旧展示。旧 @1/@2、现有安装及固定旧包不自动切换或覆盖，选择 @3 仍沿原能力接入和完整文件绑定升级。工程验证与浏览器观察范围见公开源码中的实现摘要 `docs/V2_9_IMPLEMENTATION_TRACKER.md`（不属于通用运行包）；本地原始证据不随源码提交。旧部署未自动升级，未合并 main 或发布，原 R3 不变。


可选 `local-dashboard@4` 的使用指南随独立能力包交付，具体选版见[能力接入说明](../examples/capability-adapters/README.md)。它区分内嵌／外置显示地址，外置页按实际支持提供画中画和全屏；Chat 使用宿主浏览器工具打开相应地址。页面不能自行移入 Codex 侧栏，不通过 User-Agent 承诺识别所有宿主。文案简化不改变 @3 的累计进度与当前有效验收口径，旧版及旧部署保留。
