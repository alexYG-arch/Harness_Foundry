# Harness Foundry 使用指南

这份指南面向希望用 Codex 为自己的项目搭建 Harness 的使用者。
运行包、案例需求和本文说明不自动启动任务；先确认要做什么，再批准具体执行范围。

## Foundry 与 Harness 的关系

Foundry 是搭建工具，Harness 是为某个项目生成的工作环境与规则。

例如，你有一份任务管理工具的 PRD：

1. Foundry 与你澄清需求，生成供你审阅的搭建文档。
2. 确认文档并批准运行后，Codex 建立项目规则、任务计划、检查程序和继续工作的说明。
3. 之后 Codex 在这个 Harness 中开发应用，按项目要求检查结果并处理缺陷。

仅“生成了 Harness”不自动等于“业务应用也已开发完成”。要做完应用，应把实际开发、
检查和交付一并写进搭建文档与运行范围。交付文件名和技术方案由项目需求决定，
不是固定生成某一种目录模板。

## 环境与依赖

| 项目 | 普通使用是否需要 | 说明 |
|---|---|---|
| Python 3.11+ | 需要 | Foundry 通用运行包只用标准库；当前实际使用的 Python 为 3.13.3 |
| Codex 客户端与可执行程序 | 需要 | 打开运行包目录进行交互；任务执行还需要兼容的 `codex exec`、权限配置与原生沙箱接口 |
| Codex 登录与模型使用权限 | 需要 | 使用你自己的账号和可用模型，模型由具体运行范围明确指定 |
| 网络 | 模型调用需要 | 模型服务会接收声明的输入和代码；本地任务命令默认不联网 |
| 项目工具链 | 按项目需要 | 例如 Node.js、编译器或项目测试依赖；需提前安装并明确声明 |
| 第三方 Python 库 | Foundry 运行不需要 | 项目可能另有依赖；开发 Foundry 本身则有独立的测试依赖 |
| Git | 源码开发或项目需要时 | 使用解压后的运行包不以克隆作者仓库为前提 |

### Codex 安装和登录

如果已有可用的 Codex，不必重复安装。尚未安装时，按照
[OpenAI 官方 Codex CLI 文档](https://learn.chatgpt.com/docs/codex/cli)
选择安装方式，并在首次运行时登录。官方提供独立安装器、npm、Homebrew 等方式；
Node.js 不是 Foundry 的依赖，仅在选择 npm 安装方式或项目本身需要时准备。

在终端中检查客户端：

```bash
codex --version
```

桌面客户端已提供可执行程序但它不在 PATH 时，不代表必须重复安装：
让 Codex 在准备阶段定位实际程序，并明确显示其绝对路径。
Foundry 不携带账号、API Key 或模型。使用已有 Codex 登录时，不要求为了 Foundry 再配置一套 Key。
是否能使用某个模型取决于你的账号和客户端；不能悄悄换成其他模型。

### 系统与客户端兼容性

当前实际运行环境为 **macOS / Python 3.13.3 / Codex 0.155.0-alpha.9.2 / GPT-6 Astra**。
这不是要求人人固定安装某个 alpha 版本，而是说明当前兼容性依据。
其他版本需先检查实际 CLI、权限配置与沙箱是否兼容；版本更高不自动表示接口兼容。

原生模型接入目前使用 POSIX 主机能力。Linux 的源码 CI 通过不代表完整原生运行已经支持；
Windows 也不是本版已支持的同等执行环境。不要为了启动而关闭沙箱。

在 macOS 中，运行包、输入、独立检查器、控制库和目标目录不要放在共享 `/tmp`
或其 `/private/tmp` 别名下。选择普通独立项目目录，并在运行前检查实际读写限制。

系统或项目中的额外 Codex 配置、插件、MCP、浏览器和联网任务不自动继承到 Foundry 子任务。
本版受控执行器不是任意插件/联网工作流的通用透传器；这类需求应先检查是否可实现，
不要把“PRD 中写了”当作已经具备对应能力。

## 第一次使用

### 1. 获取运行包

打开 [v0.2.0 Release](https://github.com/alexYG-arch/Harness_Foundry/releases/tag/v0.2.0)，
下载 Assets 中的 `Harness-Foundry-0.2.0-generic-3c52c30.zip`，保留隐藏的 `.agents/` 目录完整解压。

不要把 GitHub 自动生成的 Source code ZIP/TAR 当成运行包：
它们包含开发源码、历史模块和工程资料，面向维护者。

在 Codex 中把解压目录作为项目打开。仓库内的 `harness-foundry-build` Skill 和
`AGENTS.md` 提供接入说明，无须全局安装 Skill。

### 2. 只读检查入口

在解压目录运行：

```bash
python3 tools/hffactory.py version --json
python3 tools/hffactory.py --help
```

预期版本信息包含 `implementation_version: 0.2.0` 与
`product_route: GENERIC_REVIEWED_BUILD`。这两条命令不会创建业务工程或调用模型。

### 3. 准备材料并发起需求

新项目提供完整 PRD、技术偏好、平台、交付形式和约束；已有项目提供代码位置、
变更说明、必须保留的 API/行为、已有测试和不能覆盖的改动。
没有完整 PRD 也可以先对话梳理，但重要决定不应由 Agent 默默补齐。

可以这样发起：

```text
使用本目录的 harness-foundry-build Skill 为我的项目搭建 Harness。
材料是我提供的 PRD、开发要求和现有项目说明。
请先完整阅读并提出必要问题，然后保存、展示版本化搭建文档。
我确认文档前，不创建目标工程，也不开始搭建。
```

Codex 应展示实际文档，而不是只说“需求已确认”。重点检查功能、输入输出、
项目依赖、交付物、成功/失败的判断方式和需要你决定的问题。

### 4. 确认文档与执行范围

文档确认后，Codex 会准备计划与检查方式，并展示：

- 实际模型和服务，以及会发送哪些材料。
- Codex、Python 和项目工具的实际程序路径。
- 哪些目录可读、哪些可写，目标工程在哪里。
- 如何独立检查结果。
- 总尝试次数、每任务次数、单命令超时和到期时间。

确认的是这份具体范围，而不是“允许做任何事情”。范围内的任务拆分、普通实现选择、
调试与继续不逐项打断；改变需求、增加预算或扩大权限时才需要新的决定。

### 5. 获取并使用生成的 Harness

完成时，要求 Codex 展示：

- 目标工程位置与入口说明。
- 项目规则、需求/任务映射和检查命令。
- 已完成内容、已知问题和继续工作的方式。

然后按生成工程的说明打开目标项目，在 Codex 中实际使用它。
不要把 Foundry 自身目录、输入材料、独立检查器或控制库当成业务代码写入区。

以下是职责分离示意，不是要求你在确认前手工创建这些目录：

```text
Foundry 运行包       搭建工具本身
项目材料            PRD、已有代码等输入
控制与独立检查      状态记录、检查程序；位于业务写入区之外
目标工程            生成的 Harness，以及明确包含在任务内的业务产物
```

## 案例说明

### 案例一：从 PRD 建设 Task CLI 新工程

**适合：** 有明确小型需求，想从零建立开发规则并让 Codex 完成应用。

材料：[Task CLI PRD](../examples/task-cli/PRD.md)。它描述一个本地单用户任务管理工具，
使用 Python 标准库和 JSON 文件，不需要账号、服务端或数据库服务。

你可以对 Codex 说：

```text
以 examples/task-cli/PRD.md 为需求，先生成搭建文档。
目标是建设 Coding Harness，再由 Codex 使用它开发完整的任务管理 CLI。
保留 PRD 的全部业务要求，先把目标目录、交付物和运行范围展示给我。
```

预期业务产物包括 `tasks.py`、使用说明和测试；Harness 提供相应工作规则、检查入口和继续说明。
应用开发完成后，以下命令应在生成应用的目录中可用，不能直接在未建设的 examples 目录运行：

```bash
python3 tasks.py --store tasks.json add "写报告"
python3 tasks.py --store tasks.json list
python3 tasks.py --store tasks.json complete 1
python3 tasks.py --store tasks.json list --status done
python3 tasks.py --store tasks.json delete 1
```

这展示的是“需求 → Harness → 实际开发与使用”的过程，而不是下载一个已经写好的任务应用。
JSON 持久化、删除后 ID 不重用、无效输入和损坏文件处理均以 PRD 为准。

### 案例二：为已有 CSV 工具增加功能

**适合：** 已有代码可用，需要增加能力，同时不破坏原行为和用户改动。

材料：[CSV 项目说明](../examples/csv-increment/PROJECT_BRIEF.md)及其
[starter 起始代码](../examples/csv-increment/starter/csv_tool.py)。
起始工程只有 `summary` 功能；新增目标是 `audit`，用于检查 CSV 必填列缺值。

你可以这样发起：

```text
使用 examples/csv-increment/PROJECT_BRIEF.md 和 starter 目录，
为既有项目搭建 Coding Harness，并在独立目标副本上实施 audit 增量。
保留 summary、公开 API、原测试和 USER_NOTES.md，不修改输入 starter。
先展示搭建文档，再展示运行范围。
```

增量开发完成后，在生成应用目录对你准备的 CSV 文件使用：

```bash
python3 csv_tool.py summary input.csv
python3 csv_tool.py audit input.csv --required name --required email
python3 csv_tool.py audit input.csv --required email --strict
```

CSV 须包含指定列。普通 audit 输出缺值报告；`--strict` 发现缺值时退出码为 3，
输入或参数错误为 2。该功能只读取 CSV，不改写原数据。准确字段、顺序和错误处理见项目说明。

### 迁移到自己的场景

把案例材料换成自己的完整需求和项目资料即可开始澄清与文档设计，不需要修改 Foundry 核心。
可以设计本地文档处理、数据转换或多阶段质量检查等流程，但这些不是本版自带的成品模板；
外部服务、工具和可验证结果仍需逐项目确认。没有必要为一次简单脚本任务强行搭建复杂 Harness。

## 中断后继续与常见问题

**关闭会话后怎么继续？** 保留工程和控制库，告诉 Codex 原项目位置、控制库位置与 Program ID，
先读取保存的状态再判断下一步。原范围有效、预算足够且结果可确认时可以继续；
过期或结果未知时先说明原因，不重置记录或盲目重跑。

维护者可用只读命令查看状态，替换为实际路径和 ID：

```bash
python3 tools/hffactory.py read-build --control-db "/absolute/path/control.sqlite3" --program-id "YOUR-PROGRAM-ID" --json
```

**为什么需要确认两次？** 文档确认“做什么”，执行范围确认“用哪些工具、花多少预算、改哪里”。
之后的普通任务不需要逐个批准。

**只安装 Python 就能生成 Harness 吗？** 不能。Python 负责控制与本地处理，实际推理和开发还需要可用的 Codex 与模型服务。

**提示权限或依赖不足怎么办？** 先定位缺失的工具、只读文件或配置，再展示必要变更。
不要开放整个用户目录、关闭沙箱，或让模型反复重试同一个环境错误。

**旧的 Freeze/Generate 流程还能用吗？** 不能，新建只使用通用 Build。
旧记录保留只读；新程序不自动迁移旧控制库或继承旧批准。

**怎样升级？** 下载新版本到独立目录，保留旧版本和状态，阅读该版本兼容性说明。
替换代码不撤销已经发生的外部效果，也不自动恢复过期的运行范围。

## 仅维护 Foundry 源码时需要的开发依赖

普通运行包用户跳过本节。只有在完整源码检出目录维护 Foundry 时，才准备开发环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[test,security]'
python -B tools/check_release_source.py --report build/my-source-checks.json
python tools/validate_skill.py
```

报告路径必须尚不存在；再次运行时换一个文件名。
`test` extra 声明 jsonschema，`security` extra 声明 cryptography；
历史 `runtime-audit` extra 另含 referencing。它们不属于通用运行包依赖。
部分历史全量回归另依赖只读规范资料，不能把这些维护者要求套到普通使用者身上。

更多底层资料：[Build CLI](GENERIC_BUILD_CLI.md)、[运行控制](GENERIC_BUILD_RUNTIME.md)。
普通问题在 [Issues](https://github.com/alexYG-arch/Harness_Foundry/issues) 提交去敏复现；
安全问题使用 [私密报告](../SECURITY.md)。
