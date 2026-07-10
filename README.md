# Harness Foundry v2.8 Chat Factory v0.1

这是与 `Harness_Foundry_v2_8_Start_Package` 并列的工程化 Authoring Factory。用户在 Codex Chat 中提出 Agent、Harness 或 Hybrid 需求；Codex 负责语义澄清，Factory 负责确定性状态、Hash、冻结、编译、静态校验和候选发布。

唯一成功终点是：

```text
START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW
AUTHORING_STOP
```

它不批准 Start Package，不注册或启动 Program Driver，不执行 Workpack，不搭建三工程，不构建或安装 Harness，也不签发 Linkage/Conformance 结论。三工程、Driver、P3 防跳、Release、Authorization、Loop、Repair、Invalidation 与 Reentry 必须完整出现在候选包中，但保持 `PLANNED_NOT_STARTED`。

## 在 Codex Chat 中使用

1. 将本目录作为 Codex 工程打开。
2. 用自然语言描述目标、资料路径和期望的候选输出路径。
3. Codex 自动使用 repo-local `harness-foundry-start-author` Skill，并通过 Factory CLI 保存每轮状态。
4. 每轮最多回答三个最高优先级问题。
5. Readback 完整后，Factory 生成绑定 Requirement IR Hash 的确认口令；只有用户在后续消息中逐字回复该口令才会冻结。
6. 冻结后 Factory 在 staging 中生成、校验、写入有证据的 Validation Report、复验并原子发布；随后硬停在人工审阅。

权威状态不依赖 Chat 历史。换一个 Codex Chat 后，只需给出 `program_id`，Codex 会从 SQLite 恢复。

## 运行实例

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

## 关键安全性质

- 只接受固定 sibling 2.8 规范根；逐文件 Hash、整体 Hash、版本、validator 身份均锁定。
- 本地来源默认只读引用并绑定 Hash；可显式选择不可变快照。HTTP URL、Connector、Plugin、MCP 不在 v0.1 输入范围。
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
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

可选的 editable install：

```bash
python3 -m pip install -e .
hffactory verify-spec --json
```

CLI 是 Codex 的工程接口，普通用户不需要手动组织请求。完整 Envelope 与恢复规则见 [Chat 使用说明](docs/CHAT_USAGE.md)；架构见 [Architecture](docs/ARCHITECTURE.md)。
