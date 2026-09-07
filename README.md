# Harness Foundry v2.9 Chat Factory v0.2

这是按 v2.9 协议实现的本地工程化 Foundry。默认画像是 `SELF_USE_LOCAL_TRUSTED_OPERATOR`：单一可信用户在可信本机完成 Requirement/Architecture 输入、双锁编译、通用状态推进、Checkpoint/Resume、解释停止、本地可移植打包和实现证据投影。

核心产品完成条件是：

```text
41 CORE IMPLEMENTATION CAPABILITIES
OFFICIAL CORE VALIDATION PASS
PORTABLE LOCAL STARTUP SMOKE PASS
```

核心交付不要求生成 Start Package Candidate，不要求创建 Execution Root，也不要求 Runtime Bind、Program Driver、Workpack、A3、三工程、动态攻防、外部 Trust Anchor、独立认证或目标安装。最低工程安全仍保留路径 containment、凭据排除、非法输入拒绝、幂等副作用、Checkpoint/Resume 和主要失败路径回归。

Slices 09–14 的 Candidate 生成、控制面注册、Driver Runtime 验证、受控 Workpack Runtime 和 Main Package 验证实现仍保留，但归类为非默认、非核心阻塞的兼容扩展。它们不会被 `validate-core` 执行，也不能替代 Foundry 核心实现。

## 核心本地使用

无需创建 Program 或 Candidate 即可验证产品、查看版本并生成可迁移本地包：

```bash
python3 tools/hffactory.py version --json
python3 tools/hffactory.py validate-core --json
python3 tools/hffactory.py project-core-evidence --json
python3 tools/hffactory.py package-local --json
```

## 可选 Start Package 兼容路线

只有用户明确选择兼容路线时，才进入以下 Authoring 流程：

1. 将本目录作为 Codex 工程打开。
2. 用自然语言描述目标、资料路径和期望的候选输出路径。
3. Codex 自动使用 repo-local `harness-foundry-start-author` Skill，并通过 Factory CLI 保存每轮状态。
4. 每次 Requirement 更新后调用 `advance-authoring-until-gate`，自动完成内部分类、覆盖、策略、Architecture、证据适用性和 Readback 推进，不用逐步回复“继续”。
5. 只有缺失用户信息、外部状态变化、权限扩大、不可逆风险或精确 Requirement/Architecture Lock 等真实门才返回用户；阻塞问题每轮最多三个。
6. Readback 完整后，Factory 生成绑定 Requirement IR Hash 的确认口令；只有用户在后续消息中逐字回复该口令才会冻结。
7. 冻结后 Factory 在 staging 中生成、校验、写入有证据的 Validation Report、复验并原子发布；随后硬停在人工审阅。

权威状态不依赖 Chat 历史。换一个 Codex Chat 后，只需给出 `program_id`，Codex 会从 SQLite 恢复。

显式启用[预构建代理委托](docs/PREBUILD_DELEGATION_PROTOCOL.md)的 Program，
可用 `prepare-execution-handoff --program-id <program_id> --json` 只读核对并投影
已审计的 Candidate 决策。它不批准执行、不创建 Execution Root，也不启动 Driver
或 Workpack。执行启动链的已验证范围与剩余工作见
[启动链修复计划](docs/EXECUTION_STARTUP_REPAIR_PLAN.md)。

另行授权的本地运行阶段可使用[公开运行时授权入口](docs/LOCAL_RUNTIME_AUTHORIZATION.md)
展示完整 Parent 范围、记录真实用户批准或撤销授权。批准只初始化控制库并登记
Parent，不自动运行命令，也不代表 Lab、Workpack 或目标 Harness 已完成。

## 兼容路线运行实例

```text
runs/<program_id>/
├── factory.sqlite3
├── FACTORY_STATE.json
├── sources/
├── requirement_ir/
├── decisions/
├── staging/
├── validation/
└── readback/
    └── EVENTS.jsonl
```

SQLite 是权威 Event Store；JSON/JSONL 是可再生成的只读视图。每个修改请求使用 CAS State Hash、幂等键和事件 Hash 链。生成 staging 位于目标目录同一文件系统的隐藏 sibling，以保证最终 `os.replace` 原子发布。

## 兼容路线的附加安全性质

- 只接受固定 sibling 2.8 规范根；逐文件 Hash、整体 Hash、版本、validator 身份均锁定。
- 本地来源默认只读引用并绑定 Hash；可显式选择不可变快照。HTTP URL、Connector、Plugin、MCP 不在 v0.2 输入范围。
- `program_id`、`target.id` 和所有输出路径经过路径安全与重叠检查；规范、Factory、runs 和来源目录不可作为输出。
- 冻结后变更必须 `REOPEN`，进入新 epoch，并选择新的空输出路径；旧候选不被覆盖。
- Codex executor、最终 Runtime 与 Build Program Driver 分离；未确认的 CLI argv 不会被伪造，Python/Harness 自报不能证明 Codex 调用。
- 候选内没有模板文件名、占位符、假 Hash、`PLANNED-REF` 或预授权执行状态。
- 每个 Intent Atom 在冻结 IR 中绑定项目 Workpack、Stage、可选 Release Step 与 Owner；用户可在 Readback 中调整，编译器不得事后改路由。
- 独立只读 validator 覆盖固定清单、双向 traceability、P3、20 节点三工程 DAG、23 节点发布顺序、16 个项目 Workpack 的依赖来源/产出/命令/Capsule/Result/Loop/Hash 闭环、权限、Loop/Repair、伪回执和 Authoring Stop。

## 开发与验证

无需安装即可从仓库运行：

```bash
python3 tools/hffactory.py verify-spec --json
python3 tools/validate_skill.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

可选的 editable install：

```bash
python3 -m pip install -e .
hffactory verify-spec --json
```

## 本地可移植运行

`package-local` 使用固定产品 allowlist 生成不含 `runs`、SQLite、Candidate、Execution Root、凭据、缓存和本机绑定的本地包。未提供输出目录时只做预检；输出目录必须不存在。生成后会在新位置直接运行版本命令和诊断型 self-check，无需安装：

```bash
python3 tools/hffactory.py package-local --json
python3 tools/hffactory.py package-local --output-root /path/to/new-empty-package --json
python3 /path/to/new-empty-package/tools/hffactory.py self-check-diagnostic --package-root /path/to/new-empty-package --json
```

`self-check-diagnostic` 只报告便携清单、Hash、依赖、路径 containment 与本地启动状态；它不是安全 Authority，不能签发认证、批准 Candidate 或证明自身可信。

## 核心实现验证

实现完成后运行只读的官方核心行为矩阵和确定性证据投影：

```bash
python3 tools/hffactory.py validate-core --json
python3 tools/hffactory.py project-core-evidence --json
```

`validate-core` 将每项核心能力绑定到真实实现模块 Hash、公开入口、产品 Manifest Hash 与精确官方测试选择器。`project-core-evidence` 只生成可复核的实现证据投影；它不是 Release Receipt，不创建 Authority，也不声明外部认证。`SELF_USE_LOCAL_TRUSTED_OPERATOR` 画像下可选安全加固状态为 `NOT_RUN`。

核心矩阵固定为 41 项。保留的 8 项 Candidate/Runtime 兼容扩展记录为 `NOT_RUN`、`default_route=false` 和 `core_release_blocking=false`；如需使用，必须另行授权和验证。

版本、核心编译和诊断入口只要求 Python 3.11+。旧 Candidate 签名、生成与验证路径若被单独使用，需要显式安装 `.[security]`；此可选依赖不属于默认本地启动前置条件。

完整源码回归需要在开发虚拟环境安装 `.[test,security]` 后运行
`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`。
`test` extra 提供完整 Draft 2020-12 实例验证，仅用于开发测试，不增加产品默认运行依赖。
算子族和负例依赖修复的范围、验收边界见 [epoch 26 源码修复记录](docs/FOUNDRY_EPOCH26_OPERATOR_FAMILY_REPAIR_20260906.md)。

CLI 是 Codex 的工程接口，普通用户不需要手动组织请求。完整 Envelope 与恢复规则见 [Chat 使用说明](docs/CHAT_USAGE.md)；架构见 [Architecture](docs/ARCHITECTURE.md)。
