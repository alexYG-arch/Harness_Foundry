# 资源接入示例

本例把既有临时目录、SQLite、产品运行副本、结构化报告和可选本机 HTTP 服务接到同一条公开 Build 控制链。全部业务数据是合成数据，Python 标准库足够，不需要 pytest、外部账号或模型服务。默认 `network.mode=NONE`，检查器不会建立监听或发出网络请求。

这些文件是可审阅输入，不是批准或独立控制器；不会自行创建 Program、写控制库或推进真实项目。准备与批准仍使用[公开 CLI](../../docs/GENERIC_BUILD_CLI.md)及[搭建文档 Review](../../docs/GENERIC_BUILD_PLAN.md#搭建文档与人工-review-统一入口2026-09-19)。

## 文件与运行方式

| 文件 | 用途 |
|---|---|
| [PROJECT_BRIEF.md](PROJECT_BRIEF.md) | 完整合成要求及可核对的公开验收合同 |
| [request.template.json](request.template.json) | 完整 Requirement IR 和 Plan 1.2；尚不含真实 document_review 或 CLI 事件字段 |
| [scope.template.json](scope.template.json) | 完整离线 scope 字段；路径、Python 依赖和到期时间必须替换 |
| [starter/tools/summarize.py](starter/tools/summarize.py) / [rows.json](starter/fixtures/rows.json) | 产品与输入，仅复制到独立目标工作区 |
| [verifier/check_resources.py](verifier/check_resources.py) / [expected.json](verifier/expected.json) | 独立 unittest 检查器与预期数据，由 prepare 复制到宿主保护区 |

LOCAL 任务只运行 `python -I -B tools/summarize.py --output outputs/summary.json`，`python` 来自 scope 的明确绑定。检查器通过 `executable://python` 收到同一个原始解释器路径，再用它执行产品副本；不猜测 PATH 或子进程的 `sys.executable`。

产品副本显式复制工具、输入和已生成的 summary 三个普通文件，只有 `.cache`、`build` 两个生成目录可写。`tempfile` 和 SQLite 数据库写本次 `FOUNDRY_SCRATCH_DIR`；检查器不修改正式产品。预期值实际从 `FOUNDRY_VERIFIER_ROOT/expected.json` 读取，不能用产品侧的同名文件替换判定。

unittest 中产品业务断言失败写 `FAIL` 和 `failure_kind=ASSERTION`；资源可用性、服务身份/关闭等断言以及启动异常、超时、SQLite 异常或产品子进程异常退出进入 `ERROR`，保留原 traceback，不据此要求修复摘要产品。报告还记录实际 `tests_run`、错误、Case/command 身份、产品和检查器位置。最终接受由宿主核对完整报告及其绑定，不由脚本自报 PASS 决定。

## 通过已有入口接入

1. 保留原例子，规划工作区外的控制库、资源根和独立目标目录，列出将接入的 `starter/` 内容及目的路径。此时不创建目标目录或复制输入；不要把 Foundry 源码或真实项目作为本例的可写目标。
2. 结合目标环境审阅 `PROJECT_BRIEF.md` 和模板，输出版本化搭建文档并取得真实人工 Review。`request.template.json` 的来源清单指向 `PROJECT_BRIEF.md`，来源采集应完整读取它；若改写要求或行号，同步公开合同定位。模板没有预造 `document_review`、确认消息或令牌。
3. 将实际绝对目录、原生 Codex receiver、既有项目 `.venv/bin/python` 及它所需的只读标准库/动态库目录填入 scope。资源根不得与工作区、检查器、控制库或其依赖目录重叠。原生接入支持情况以当前 receiver 预检为准；无法提供沙箱时沿既有报错返回，不另建直跑后门。示例预算 3 和超时 30 秒仅是可调整的案例值，不是新通用限制。
4. 在正式 `record-build-plan` 请求中加入真实 `document_review`、`expected_revision`、`idempotency_key`；然后 `capture-build-sources` 绑定 `PROJECT_BRIEF.md`，`prepare-build-authorization` 使用本 scope。事件 ID 和 revision 使用前一步实际返回值，不能从示例或测试中抄写。每个请求的完整业务字段见公开 CLI 表。
5. 展示 prepare 的完整 Readback，包括受保护检查器副本、产品副本清单、写域、网络、预算和期限；先前文档及本次运行说明也应包含已展示 `starter/` 的接入准备。取得针对该准备事件的真实后续用户批准并通过既有 `approve-build-authorization` 记录后，由宿主把 `starter/` 内容复制到选定目标，形成 `product/tools/` 和 `product/fixtures/`，再调用 `advance-build`。这是该次批准所包含的接入准备，不增加新批准类别，也不把复制源代码授权给输出目录中的 LOCAL 任务。本例选择或源码测试的通过不代替真实运行批准。
6. 用 `read-build --control-db 实际绝对路径 --program-id 实际ProgramID` 取回结果。`PLAN_CHECKS_ACCEPTED` 仅表示该合成计划的已声明检查被接受，不代表真实项目、完整 Harness 或发布验收。固定 LOCAL 生成器不会自行理解新修复目标；业务失败应检查差异并沿原变更/修复入口处理，不反复重跑未改变的生成器。

上面说明使用既有流程，没有新增逐步批准。源码测试可在隔离临时目录使用标明为测试数据的审批 fixture；该 fixture 不能用于真实 Program。

## 可选本机 HTTP 变体

在准备和批准前，从离线模板选择本机变体，作以下对应替换：

- 将 `verification_resources.profiles.offline` 改名为 `local-tcp`，将该 profile 的 `network` 改为 `{"mode":"LOCAL_SERVICE","tcp":"LOOPBACK"}`。
- 将 `required_checks` 改为 `["product","temp","sqlite","service"]`。
- 将唯一 verification 的 `resource_profile_ref` 改为 `local-tcp`，argv 最后一项从 `offline` 改为 `tcp`；其他 argv 和文件清单不变。

选择一种 profile 即可，离线模板没有未使用的联网配置。已批准范围的网络变化仍按现有范围变更流程处理，不能静默改模板后继承旧批准。

TCP 检查器绑定 `127.0.0.1:0` 一次，读取自己的实际端点，并以本次 `FOUNDRY_COMMAND_ID` 核对响应；不会寻找或连接未知常驻服务。HTTP 客户端直接连接该端点，不使用继承的 HTTP 代理。无论断言通过还是失败，`finally` 都关闭连接、监听器并等待线程结束；异常启动不借用其他服务。超时或撤销继续由宿主管理原命令进程组。

当前原生 `tcp: LOOPBACK` 权限实际包含回环 **TCP 和 UDP 的全部端口**，不隔离其他本机服务；外部还有原生端口 53 例外，且不验证该端口承载的是否为 DNS。原生绑定能力也允许 wildcard，示例本身只使用 `127.0.0.1`。这些是实际能力边界，不应宣称“只准这个 HTTP 实例/端口”或“TCP-only”。本例的 HTTP 通过不等于 UDP 业务验收或公网服务验收。

## 证据、恢复与清理

宿主把 `summary.json` 归档到原 command 观测目录并持久化资源结果，再按既有成功清理规则清理暂存区和产品副本；失败证据保留。`failure_days=7` 是保留声明，当前没有自动到期清理器。示例检查器只主动清理自己建立的临时小目录、SQLite 连接和 HTTP 实例，不自行删除宿主资源根。

中断后先用 `read-build` 查看原 attempt/command 和观测附件，再经既有 `advance-build` 恢复。完成 capture 或已有资源结果时只恢复采集/结算，不重放已完成的产品或检查命令、不重新复制产品、不另计一次 attempt。缺失或未知事实沿原恢复规则处理，不能靠新 Program 清零。

正常接受和恢复都会按原命令清单核对已声明复制输入的源版本；改变其中任何一个源输入时，旧报告保留但不能当成新版本的通过证据。未声明的工作区文件不会因此新增检查或失效规则；恢复不会重新读取已清理的副本。

本例只演示标准库和既有资源能力。源码/隔离进程测试、原生沙箱测试、真实用户项目验收应分别报告；没有真实外部服务、凭据、生产数据库、递归目录复制或长期 sidecar 的验收结论。协议保持 2.9，不新增资源字段、G1/G2 规则、审批器或通用限制，也不执行发布。
