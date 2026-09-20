# Harness Foundry v2.9 Chat Factory v0.2

Foundry 用于搭建由 Codex Agent 控制运行的通用 Harness：约束输入输出、依赖、权限和
独立验收；推理与实现方式由 Agent 在范围内选择，确定性阶段可由本地程序处理。

## 新建统一使用通用 Build

2026-09-20 用户决定停止维护旧的新建流程。开发入口与通用发行包统一采用
`GENERIC_REVIEWED_BUILD_ONLY`，不再提供可选 Start Package/Candidate/epoch 新建路线。

1. 读取完整需求、PRD 或现有项目资料，保留澄清问答。
2. 输出并展示版本化搭建文档，等待用户确认实际版本和范围。
3. 编制 Requirement/Plan、来源和独立检查；展示模型、目录、工具、预算、到期时间，
   获得真实运行范围批准。
4. 在批准范围内自动实施、独立检查、有限修复、推进和恢复，不逐 Workpack 要求批准。
5. 报告实际验收范围和缺陷；模型完成、文件生成或源码测试通过不等于完整 Harness 可用。

详见[搭建文档合同](docs/GENERIC_BUILD_PLAN.md)、[Build CLI](docs/GENERIC_BUILD_CLI.md)
和[运行控制](docs/GENERIC_BUILD_RUNTIME.md)。源码工程和只读诊断不因此增加人工门禁。

```bash
python3 tools/hffactory.py version --json
python3 tools/hffactory.py --help
```

普通用户向 Codex 描述需求即可，无须手写 JSON 或复制 Hash。文档确认不暗含执行批准，
原始 PRD 不是直接启动指令；旧批准、代理委托和后台 PASS 均不能替代真实用户决定。
`compile-build-plan` 只是无状态检查，不创建 Program、目标目录或运行权限。

## 历史保留，不再新建

旧 `chat-turn`、`compile`、Freeze/Generate、旧运行授权/恢复及 `package-local`
等公开命令明确返回 `LEGACY_WORKFLOW_RETIRED`，没有兼容回退或重新启用开关。
历史 Candidate、快照和数据库不改写、不自动迁移，也不将历史批准追认为新授权。

查看关闭的旧 authoring 数据库：

```bash
python3 tools/hffactory.py read-history --database /absolute/path/factory.sqlite3 --program-id ID --json
```

该命令只读原记录，不重放事件；非空 WAL 会被拒绝以免漏读未提交到主库的数据。
当前通用 `REVISION_V1` 状态仍用 `read-build`。旧内部实现及行为测试暂留开发源码作
历史回归，**不是继续维护的生产路线，也不随通用包分发**。旧 41 项验证只证明历史基线，
不能作为新版公开接口或发布验收。详见[Chat 使用说明](docs/CHAT_USAGE.md)。

## 开发验证与通用打包

通用运行依赖 Python 3.11+ 标准库；真实 Codex 运行还须在范围中声明其可执行程序、
模型/服务、本地工具与原生隔离能力。没有隐式模型切换或无沙箱降级。

完整开发环境安装 `.[test,security]` 后运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/check_release_source.py --report build/new-source-checks.json
python3 tools/validate_skill.py
```

历史源码诊断仍可运行 `verify-spec`、`validate-core`、`project-core-evidence`；
其中 sibling 规范和历史 Hash 合同不是通用运行依赖。历史测试适用断言仍保留，不用
改标签、跳过或删除用例冒充新版验收。当前公开接口另有退役/通用流程行为测试。

通用包开发预检和固定提交组装：

```bash
python3 devtools/package_generic_release.py
python3 devtools/package_committed_release.py --revision <explicit-commit>
```

默认预检不发布；固定提交组装会临时提取该提交的源码，不混入脏工作区。需要输出时按
工具帮助指定尚不存在的路径。归档只保留必要身份校验，不增加逐日志 Hash 链。
旧的 `package-local` 不再是交付入口。

## 发布边界

实现版本仍为 `0.2.0`，协议目标 `2.9`，MIT 许可，唯一正式仓库
[alexYG-arch/Harness_Foundry](https://github.com/alexYG-arch/Harness_Foundry)。
当前 `release_ready=false`：已完成限定 M1 和独立新会话重入，不代表完整 PRD 或
同一最终发行包的双案例验收。用户已确认双案例搭建文档；尚需具体运行范围批准及实际验收。

[更新说明](docs/FOUNDRY_UPDATE_2026_09_20.md)、
[发布准备](docs/RELEASE_READINESS.md)、
[通用更新计划](docs/FOUNDRY_GENERIC_CODEX_HARNESS_UPDATE_PLAN_v0_2.md)及
[Tracker](docs/V2_9_IMPLEMENTATION_TRACKER.md)区分已实现、历史证据和未闭合项。
本次入口切换不构成目标执行、Git 推送、正式发布或既有数据迁移授权。
