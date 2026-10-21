# WP09 工程候选、单能力候选与接收准备

WP09历史候选保留；当前V9按已确认调整为本机干净环境实跑＋环境差异测试，新用户和macOS虚拟机按需可选，取消第二设备义务。候选生成、完整解压和包内检查不等于目标 Harness 新任务、模型、浏览器、原生接收器或发布验收。协议保持 2.9，Plan 保持 1.2；原 R3 进度与 G1/G2 不变，不新增通用门禁。

## 两种候选分别包含什么

| 候选 | 来源与入口 | 包含内容及用途 |
|---|---|---|
| Generic 工程 runtime | 源码工作区的 [package_generic_release.py](../../devtools/package_generic_release.py)，可给出 `--output` | 按现有明确清单保存 Generic 核心、文档、构建 Skill、示例和能力准备 helpers。包含 prepare/environment/consume/upgrade、Foundry 只读看板适配，以及现有 R3 普通文件 merge/apply 及相邻依赖。各能力版本分别选择，不默认装入全部能力 |
| 单能力源码候选 | 源码工作区的 [package_capability_candidate.py](../../devtools/package_capability_candidate.py)，显式指定 `--directory`、`--version`，可给出 `--output` | 读取该目录 `capability.json` 明确声明的 materials、tools、runtime_files、verification_files；另带 LICENSE 和 `CAPABILITY_PACKAGE_MANIFEST.json`。一次只固定一个所选版本，不递归复制包外文件或整棵 SDK |

两个打包入口都不执行能力或建立业务接受。省略 `--output` 只做对应文件收集和候选预检；提供输出时须使用已存在目录下的新绝对 ZIP 路径，不覆盖旧候选。输出中给出的归档摘要对应本次 ZIP。保留这份 ZIP 及其清单，后续验证明确对应它，不把工作区后来修改的文件视为已随候选交付。

以下命令是源码工作区中的调用示意；真实路径由本次准备填写，本页不表示它们已经运行：

```sh
.venv/bin/python -I -B devtools/package_generic_release.py \
  --output /new-candidates/foundry-runtime-engineering.zip
.venv/bin/python -I -B devtools/package_capability_candidate.py \
  --directory examples/capability-adapters/packages/data-summary/1 \
  --version 1 --output /new-candidates/data-summary-1.zip
```

这些 `devtools/` 是源码侧候选生成工具，不是接收设备运行 Generic runtime 的前提，也不承诺随 ZIP 分发。正式发行仍须选择明确 Git commit/ref，沿 [package_committed_release.py](../../devtools/package_committed_release.py) 的 `--revision` 固定来源，再完成原定同包验收及发布流程；它没有名为 `--commit` 的参数。工作区工程候选不是 commit 发行包，本轮不执行 commit、tag、推送或发布。

## WP09历史选定的五个能力

| 名称与版本 | 公开调用入口 | 宿主检查与实际依赖 |
|---|---|---|
| [qt-cmake@1](packages/qt-cmake/1/guide.md) | `qt_cmake.py`，工具 ID `qt-cmake` | `check_ctest.py` 留在检查域；接收设备提供 Python 3.11+、CMake/CTest 3.21+ 和实际 Qt SDK。SDK、项目测试源码、独立必测清单、构建和报告目录由项目/宿主声明 |
| [data-summary@1](packages/data-summary/1/guide.md) | `summarize_csv.py`，工具 ID `summarize-csv` | `check_summary.py` 留在检查域；Python 3.11+。项目提供 CSV、计算口径配置和独立完整预期，不在能力包中固化业务答案 |
| [doc-export@1](packages/doc-export/1/guide.md) | `export_doc.py`，工具 ID `export-doc` | `check_doc.py` 留在检查域；Python 3.11+。项目提供结构化 notes、来源、格式配置和完整独立预期；不宣称能自动解析任意文档 |
| [host-review@1](packages/host-review/1/guide.md) | `snapshot.py`，工具 ID `snapshot-host-review`；另有 PRD/MARKET 工作流材料 | `check_review.py` 留在检查域；Python 3.11+。实际浏览器/检索仍由声明宿主完成，快照和绑定不证明观察文字的真实性或业务结论 |
| [local-dashboard@1](packages/local-dashboard/1/guide.md) | `dashboard.py`、[target.py](packages/local-dashboard/1/target-guide.md)，工具 ID `local-dashboard`、`target-dashboard`，连同声明的 `web/` 文件 | Python 3.11+ 与实际浏览器能力由接收设备提供。目标观察读取自己的明确记录；Foundry 适配另使用 runtime 内的宿主入口。启动看板只建立观察服务，不执行业务或恢复报告 |

单能力候选是**宿主侧源码包**，可能同时含公开工具和独立 checker。不能把整个 ZIP 解压目录、完整 `materials.json` 或私有检查依赖交给 producer。沿原准备器分离公开来源/工具和 `verification_files`，项目独立预期放入原保护域；真正检查使用受保护副本。只交付目标所需的公开工具、声明运行文件及项目配置。

候选不带 Qt SDK、CMake 安装、开发机 `.venv`、账户凭据、运行数据库、本机绝对环境绑定、旧接受记录或本地测试证据。候选清单中的 `environment` 只是需要解析的声明；`runtime_verified: false`、`acceptance_claimed: false` 和 `execution_authority_granted: false` 不由“ZIP 已生成”改成已验收。

## 接收设备如何使用包内入口

先将 Generic runtime 和每个显式选定能力**完整解压到各自新的普通目录**，保留旧目录、旧产物和报告。不要在旧安装或目标文件上覆盖解压，也不要只取单个脚本丢掉其相邻 helper、页面或清单。目录位置与原生读写/网络权限继续按已有运行要求选择；这不是新增安装器或额外审批流程。

接收设备重新绑定自己的 Python/`.venv`、CMake、CTest、Qt SDK 及所选工具。版本观察必须来自接收设备实际工具，不能复制开发机版本字符串。准备器解析位置、版本范围及声明依赖，不安装、不执行探测；文件存在和解析 READY 不代表原生运行成功。

| 解压后入口 | 可执行的职责 | 仍由谁负责 |
|---|---|---|
| `tools/hffactory.py version --json`、`--help` | 查看所选 Generic runtime 的版本和命令 | 不启动目标、不代表业务或原生沙箱验收 |
| `examples/capability-adapters/prepare.py` 与 `environment.py` API | 根据新设备的完整配置准备新材料、解析显式环境依赖 | 新输出独立保存；项目期望、授权与资源配置仍沿原流程 |
| `examples/capability-adapters/consume.py` | 调用前核对所选文件/版本/入口，并返回 `argv` | 不创建进程；既有授权宿主执行实际调用并记录真实消耗 |
| `examples/capability-adapters/upgrade.py` | 基于旧材料与完整的新选择，准备新材料及差异 | 不 apply，不迁移 Program，不复用旧授权为新范围授权 |
| runtime 的 `examples/harness-composition-upgrade/helpers/merge.py`、`apply.py` | 处理显式普通文件候选和应用意图，使用相邻 `file_states.py` | 不做 SDK 安装、控制状态写入或业务接受；具体语义见[原 helper 说明](../harness-composition-upgrade/helpers/README.md) |
| runtime 的 `examples/capability-adapters/foundry_dashboard.py` | 通过所选公共看板读取明确 Program/prepared 的 Foundry 记录 | 不寻找“最新运行”、不调度、不重放；local-dashboard 包需单独选择 |
| 单能力包的公开工具、目标 `target.py` | 使用项目自己的输入/配置及声明工具；目标观察不要求 Foundry 常驻 | checker 留在宿主检查域；真实业务、浏览器表现与接受分别留证 |

解压 runtime 内的 `examples/capability-adapters/README.md` 来自[可携带的 helper 说明](../../resources/generic_release/CAPABILITY_HELPERS.md)，保留包内可用链接；开发仓库本页用于说明候选准备，不依赖本机 runs 路径。实际接入参数详见[材料与消费接口](README.md)及各能力 guide。

## 独立换包和保留项目定制

新能力版本放入新目录，与旧版并存。新建项目选择新版；已有目标不因另一个包出现就自动切换。沿 [UPGRADE](UPGRADE.md) 提供完整下一阶段选择、接收设备环境和项目自身基础材料，`upgrade.py` 写新材料与差异。实际调用再用 `consume.prepare_call` 核对所选包，不只改版本名或环境表。

外部只读能力只调整明确的选择/调用绑定并复验受影响行为。实际交付到目标的可定制普通文件继续用真实 G（上次生成基线）、C（当前含定制文件）、N（新候选）合并；冲突保留三份，缺少可靠 G 时沿原项目增量路径处理，不从包源码伪造基线。项目配置、标签、记录位置和业务规则留在公共包外；不以整包覆盖替代合并。移除只处理明确拥有且不再使用的文件，共享依赖、用户定制和旧报告保留。

切换观察组件后重启该观察实例采用新版本，不重启业务。能力升级、只复验、原接受复用与报告捕获恢复仍交原 controller 按实际条件判断；重新检查与读取旧报告是两种动作，不能以新检查冒充零消耗恢复，也不能因换包清空累计预算。

## 本轮完成与待验收如何区分

包内准备、入口可加载、搬移目录后解析和工程夹具只支持对应的工程候选结论；实际通过范围由本轮单独实施记录报告，不在本页预填测试结果或给验收加分。历史 Qt/DATA 本机工程结果保留原范围，不因放进新 ZIP 就变成本候选或第二设备的运行证据。

历史候选保留原证据；当前Qt/DATA原生运行与升级、目标Harness新会话/新输入、实际模型/宿主、组件升级及浏览器/PiP和效果对照按当前V/F/H记录分别取证，不从本页倒推完成。本机干净环境和差异测试不证明另一台设备；不恢复跨设备义务，也不将其另记为新增豁免。原 R3 100% 保持原定义，工程候选不关闭新的完整验收项，也不增加通用限制或发布范围。

## 独立技术栈补全候选

新增可选 `qt-cmake@2` 与 `python-environment@1`。源码侧仍用同一单能力打包器，完整声明公共运行文件与独立检查依赖。通用runtime新增stack_runtime/stack_handoff/native_dependencies及格式和作者说明；不把两个包自动装入runtime。新候选、原生工程证据及实际目标验收单独记录，不替换WP10固定ZIP、Readback或预算。详细接入见 [STACK_ENVIRONMENT.md](STACK_ENVIRONMENT.md)。
