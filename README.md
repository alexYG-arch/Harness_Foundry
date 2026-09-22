# Harness Foundry

用 Codex 搭建适合你的项目的 Harness，让 Agent 按明确需求持续实施、检查、修复和继续工作。

**Foundry 搭建 Harness；生成的 Harness 再指导 Codex 完成项目工作。** 它不是另一套模型，
也不是固定行业流水线：Codex 负责理解、推理和实现，Foundry 负责输入输出约定、任务依赖、
权限、独立检查和进度保存。确定性步骤可以交给本地 Python 等程序。

[下载 v0.2.0](https://github.com/alexYG-arch/Harness_Foundry/releases/tag/v0.2.0) ·
[完整使用指南](docs/USER_GUIDE.md) ·
[案例说明](docs/USER_GUIDE.md#案例说明) ·
[问题反馈](https://github.com/alexYG-arch/Harness_Foundry/issues)

产品版本 **0.2.0**，协议版本 **2.9**，采用 [MIT](LICENSE) 许可。

## 适合什么场景

| 场景 | 你提供什么 | Foundry 帮你建立什么 |
|---|---|---|
| 根据 PRD 开发新项目 | 完整 PRD、技术要求、交付目标 | 开发规则、任务计划、检查入口和恢复说明 |
| 为已有项目增加功能 | 现有代码、变更说明、必须保留的行为 | 适配既有工程的开发流程，保护原功能和无关改动 |
| 组织多阶段本地工作 | 各阶段输入输出、依赖、判断成功的方法 | Codex 与本地程序协作的任务链、独立检查和持久进度 |

仓库附带两个可上手的示例：**Task CLI 任务管理工具**与 **CSV 工具增量开发**。
更多领域可以按需求设计，但本版不内置浏览器自动化、云部署或媒体生成流水线。

## 快速开始

### 1. 下载并打开

在 Release 的 Assets 中下载 `Harness-Foundry-0.2.0-generic-3c52c30.zip`，
解压到普通独立项目目录，并用 Codex 打开该目录。

请使用这个通用运行包，而不是 GitHub 自动生成的 `Source code.zip`。
不用安装为全局 Skill，也不需要把整个开发仓库复制到你的业务项目。

### 2. 检查环境

在解压目录运行：

```bash
python3 --version
python3 tools/hffactory.py version --json
python3 tools/hffactory.py --help
```

- **Python 3.11+**；通用运行包仅依赖 Python 标准库。
- **可用且已登录的 Codex**，以及能够调用的模型；真实执行需可用的 Codex 可执行程序和原生沙箱。
- 当前实际使用环境为 macOS、Python 3.13.3、Codex 0.155.0-alpha.9.2、GPT-6 Astra。
  其他客户端版本需要先核对接口和权限；Linux/Windows 暂不承诺同等运行支持。
- macOS 下不要把运行包、输入或目标放在共享 `/tmp` 或 `/private/tmp`。
- 项目自己的工具链按项目需要准备，并不是 Foundry 的默认依赖。

安装方式、账号、网络和开发依赖的区别见[环境与依赖](docs/USER_GUIDE.md#环境与依赖)。

### 3. 向 Codex 描述目标

可以直接复制以下内容，替换材料位置：

```text
请使用本目录的 harness-foundry-build Skill，
基于我提供的 PRD 和开发要求，为项目搭建 Coding Harness。

先完整阅读材料、澄清缺口，输出带版本的搭建文档给我确认。
文档应说明目标、交付物、工作流程、工具与目录，以及怎样判断结果正确。
我确认文档后，再展示具体运行范围；不要直接开始搭建。
```

不需要手写内部 JSON、复制冻结令牌或手工管理 Hash。

### 4. 确认后自动推进

你先确认搭建文档，再批准展示的模型、工具、读写目录、次数预算和期限。
随后 Codex 在该范围内自动实施、独立检查、修复和继续，不逐任务请求批准。
需求改变、预算耗尽、权限不足或结果不明时会停下说明原因。

完成后，按生成工程的入口说明使用 Harness；需要在其中继续开发业务程序时，
明确相应任务和运行范围。详细步骤见[完整使用指南](docs/USER_GUIDE.md)。

## 内置案例

- **新项目：Task CLI。** 根据完整小型 PRD 搭建 Coding Harness，再用它开发本地任务工具：
  新增、列出、完成、删除任务，并保存 JSON 数据。[查看 PRD](examples/task-cli/PRD.md)。
- **已有项目：CSV 增量。** 为已有 CSV 汇总工具增加必填列检查，保留原命令、API、测试和用户笔记。
  [查看项目说明](examples/csv-increment/PROJECT_BRIEF.md)。

`examples/` 提供的是需求和起始代码，不是已搭建好的业务程序；案例中的具体用法和预期产物见
[案例说明](docs/USER_GUIDE.md#案例说明)。

## 说明与支持

- [使用指南](docs/USER_GUIDE.md)：接入、依赖、案例、继续工作和常见问题。
- [v0.2.0 更新说明](docs/releases/v0.2.0.md)：本版能力、下载和兼容性。
- [Build CLI](docs/GENERIC_BUILD_CLI.md)：为接入工具或维护者提供的底层接口，不是初次使用的必读材料。
- [安全报告](SECURITY.md)：漏洞请使用私密报告，不在公开 Issue 上传凭据、私有 PRD 或原始运行记录。

新建统一使用通用 Build；旧 Start Package、Candidate、epoch、Driver 新建流程已退役。
详细的工程测试和历史记录保留在开发文档中，不是普通用户的使用步骤。
