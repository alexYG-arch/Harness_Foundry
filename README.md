# Harness Foundry

**Harness Foundry 帮你用 Codex 搭建项目专属的 Harness。** Harness 是项目的开发规则、
任务计划、检查入口和进度记录，让 Codex 按明确需求实施、检查、修复和继续工作。

Foundry 是搭建工具，不是另一套模型，也不是固定行业流水线。Codex 负责理解需求和编写代码；
Foundry 管理输入输出约定、任务依赖、运行权限、独立检查和进度记录。确定性步骤可由本地 Python 等程序执行。
搭建 Harness 与完成业务应用是两件事；如果希望一并开发应用，需要在搭建文档和运行范围中写明。

[下载 v0.5.0](https://github.com/alexYG-arch/Harness_Foundry/releases/tag/v0.5.0) ·
[完整使用指南](docs/USER_GUIDE.md) ·
[案例说明](docs/USER_GUIDE.md#案例说明) ·
[问题反馈](https://github.com/alexYG-arch/Harness_Foundry/issues)

**v0.5.0 已于 2026-10-15 发布，发布提交的 main 与 tag CI 已通过。** 协议版本保持 **2.9**，
采用 [MIT](LICENSE) 许可。既有 tag、Release 和下载包原样保留。
本轮发布来源、检查和下载复验见[工程记录](docs/V2_9_IMPLEMENTATION_TRACKER.md)。

## v0.5.0 · 验收资源与有依据的续修

- **让普通测试正常运行。** 检查器可按声明使用私有临时目录、缓存、SQLite、本机服务和必要的 HTTP(S) 调用。
- **保护正式产品与判定依据。** 需要在工程目录生成文件时使用显式产品运行副本；检查器和判定依赖来自受保护副本。
- **保留报告并安全恢复。** 测试凭据按需注入受控检查命令；日志和声明报告脱敏，恢复读取已有结果，成功后清理本次资源。
- **核实额外问题后继续修复。** 外层 Codex 负责核实、去重和停止判断；Harness 提供受控返修与单次交回，继续负责预算和独立验收。

默认离线流程保持兼容；只有项目需要时才声明额外资源。详细变化见
[v0.5.0 发布说明](docs/releases/v0.5.0.md)。原有清晰表达、`read-build --human` 和 JSON 接口保持。

## 适合什么场景

| 场景 | 你提供什么 | Foundry 帮你建立什么 |
|---|---|---|
| 根据产品需求开发新项目 | 完整产品需求文档（PRD）、技术要求、交付目标 | 开发规则、任务计划、检查入口和恢复说明 |
| 为已有项目增加功能 | 现有代码、变更说明、必须保留的行为 | 适配既有工程的开发流程，保护原功能和无关改动 |
| 组织多阶段本地工作 | 各阶段输入输出、依赖、判断成功的方法 | Codex 与本地程序协作的任务链、独立检查和进度记录 |

仓库附带三个可上手的示例：**Task CLI 任务管理工具**、**CSV 工具增量开发**与 **验收资源接入**。
更多领域可以按需求设计，但本版不内置浏览器自动化、云部署或媒体生成流水线。

## 快速开始

### 1. 下载并打开

在 v0.5.0 Release 的 Assets 中下载 `Harness-Foundry-0.5.0-generic.zip` 和 `SHA256SUMS`。
下载后，
保留隐藏的 `.agents/` 目录，解压到普通独立项目目录，并用 Codex 打开该目录。

请使用这个通用运行包，而不是 GitHub 自动生成的 `Source code.zip`。
不用安装为全局 Skill，也不需要把整个开发仓库复制到你的业务项目。
本次复用已验收的原 ZIP；包内准备阶段措辞是冻结构建记录，当前发布信息以本指南和 Release 页面为准。

### 2. 检查环境

在解压目录运行：

```bash
python3 --version
python3 tools/hffactory.py version --json
python3 tools/hffactory.py --help
```

- **Python 3.11+**；通用运行包仅依赖 Python 标准库。
- **可用且已登录的 Codex**，以及能够调用的模型；真实执行需可用的 Codex 可执行程序和原生沙箱。
- 历史原生验收在 macOS 上完成，具体 Python、Codex 和模型版本见
  [兼容性说明](docs/USER_GUIDE.md#系统与客户端兼容性)。其他版本需要先核对接口和权限；
  Linux/Windows 暂不承诺同等运行支持，源码 CI 通过不代表原生执行已验证。
- macOS 下不要把运行包、输入、独立检查器、控制库或目标放在共享 `/tmp` 或 `/private/tmp`。
- 项目自己的工具链按项目需要准备，并不是 Foundry 的默认依赖。

安装方式、账号、网络和开发依赖的区别见[环境与依赖](docs/USER_GUIDE.md#环境与依赖)。

### 3. 向 Codex 描述目标

可以直接复制以下内容，替换材料位置：

```text
请使用本目录的 harness-foundry-build Skill，
基于我提供的 PRD 和开发要求，为项目搭建 Harness。

先完整阅读材料、澄清缺口，输出带版本的搭建文档给我确认。
文档应说明目标、交付物、工作流程、工具与目录，以及怎样判断结果正确。
我确认文档后，再展示具体运行范围；不要直接开始搭建。
```

不需要手写内部 JSON、复制冻结令牌或手工管理校验值。

### 4. 确认后自动推进

你先确认搭建文档，再批准展示的模型、工具、读写目录、次数预算和期限。
随后 Codex 在该范围内自动实施、独立检查、修复和继续，不逐任务请求批准。
需求改变、预算耗尽、授权到期或撤销、权限不足或执行结果不明时会停下说明原因。

完成后，按生成工程的入口说明使用 Harness；需要在其中继续开发业务程序时，
明确相应任务和运行范围。详细步骤见[完整使用指南](docs/USER_GUIDE.md)。

## 内置案例

- **新项目：Task CLI。** 根据完整小型 PRD 搭建 Harness，再用它开发本地任务工具：
  新增、列出、完成、删除任务，并保存 JSON 数据。[查看 PRD](examples/task-cli/PRD.md)。
- **已有项目：CSV 增量。** 为已有 CSV 汇总工具增加必填列检查，保留原命令、API、测试和用户笔记。
  [查看项目说明](examples/csv-increment/PROJECT_BRIEF.md)。
- **验收资源接入。** 用临时文件、SQLite 和产品副本运行独立检查，按需启用本机 HTTP。
  [查看接入示例](examples/resource-check/README.md)。此示例随 v0.5.0 运行包提供。

`examples/` 提供的是需求和起始代码，不是已搭建好的业务程序；案例中的具体用法和预期产物见
[案例说明](docs/USER_GUIDE.md#案例说明)。

## 验证与发行进度

v0.5.0 本地完整回归 **1197/1197**、公开源码检查 **438/438** 通过，均无跳过、失败或错误。
本次发行的同一 ZIP 完成 **6 项安装位置资源检查**及真实 Codex 的受控续修、单次交回和报告交接场景。
规范与 Skill 检查通过。tag 与运行包来源为提交
[`a8312c6`](https://github.com/alexYG-arch/Harness_Foundry/commit/a8312c65a21b3fb82175e7908611d49be422da7e)；
该提交的 [main CI](https://github.com/alexYG-arch/Harness_Foundry/actions/runs/38668881367) 和 [tag CI](https://github.com/alexYG-arch/Harness_Foundry/actions/runs/38669156738) 均已通过。
Release 下载复验确认 **53 文件**，ZIP SHA-256 与已验收原包一致；隔离环境的 version/help 加载通过。
具体检查范围及完整校验值见[v0.5.0 发布说明](docs/releases/v0.5.0.md)。

以下为 v0.4.0 的历史发行记录，不代替本轮验证。v0.4.0 于 **2026-10-13** 发布，tag 和运行包均来自提交
[`c7c8b8e`](https://github.com/alexYG-arch/Harness_Foundry/commit/c7c8b8ed0a81e904f5baa42538f1f4b4b6829eaa)。
该提交的 [main CI](https://github.com/alexYG-arch/Harness_Foundry/actions/runs/38354310099)
和 [tag CI](https://github.com/alexYG-arch/Harness_Foundry/actions/runs/38354663250) 均已通过。

- **已检查：** 既有公开源码检查 **289/289 通过**，无跳过、失败或错误，Skill 引用检查
  **5/5 通过**；固定提交打包、ZIP 完整性和下载后的只读入口加载检查通过。
- **未验证：** 本版 ZIP 未重跑新项目和已有项目增量这两个真实模型案例；未新增真实模型
  表达效果评测。因此不宣称完整发行验收、普遍提速或全面稳定性提升。

既有评测中，Ledger 小样本的中位耗时降低 19.0%，Config 降低 1.2%；原 Task 失败保留，
后续两个隔离 Task 样本业务通过。这些结果仍绑定原提交和样本，不是本版 ZIP 的新增实测。
详见[评测摘要](docs/FOUNDRY_UPGRADE_EVALUATION_2026_10_10.md)和
[工程记录](docs/V2_9_IMPLEMENTATION_TRACKER.md)。CI、软件发布和项目实际验收是不同结论。

## 更新记录与支持

- [使用指南](docs/USER_GUIDE.md)：接入、依赖、案例、继续工作和常见问题。
- [v0.5.0 发布说明](docs/releases/v0.5.0.md)：资源接入、续修、下载与检查依据。
- [v0.4.0 发布说明](docs/releases/v0.4.0.md)：上一稳定版的增量、下载和检查依据。
- [v0.3.0 历史说明](docs/releases/v0.3.0.md)：保留上一版及其下载包。
- [v0.2.0 历史说明](docs/releases/v0.2.0.md)：保留旧版本的能力、下载和兼容性记录。
- [2026-10-10 升级说明](docs/FOUNDRY_UPGRADE_2026_10_10.md)：验收前置、环境预检、输入交接和失败处理；已纳入 v0.3.0。
- [2026-09-26 更新说明](docs/FOUNDRY_UPDATE_2026_09_26.md)：能力复用、接口衔接、局部修复与历史双案例验证；已纳入 v0.3.0。
- [Build CLI](docs/GENERIC_BUILD_CLI.md)：为接入工具或维护者提供的底层接口，不是初次使用的必读材料。
- [安全报告](SECURITY.md)：漏洞请使用私密报告，不在公开 Issue 上传凭据、私有 PRD 或原始运行记录。

新建统一使用通用 Build；旧 Start Package、Candidate、epoch、Driver 新建流程已退役。
详细的工程测试和历史记录保留在开发文档中，不是普通用户的使用步骤。
