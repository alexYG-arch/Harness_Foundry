# Harness Foundry v2.8 Controlled Execution Runtime v0.1

这是与 Chat Factory 分离的通用执行控制面。Factory 只产出
`START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW` 和 Hash 交接；本 Runtime
负责 bootstrap、Driver 运行时验证、独立执行授权、Workpack 循环、恢复、
迁移与 A3 连续推进。

默认模式始终是 `A1_PLAN_ONLY`。bootstrap 的一次人工审阅会消费五个彼此
独立、Hash 绑定的子授权：

- Candidate approval
- Shared baseline
- Control registration
- Driver materialization
- Runtime verification

这些子授权不包含、也不能推导 `EXECUTION_AUTHORIZATION`。只有 Driver
runtime verification 完成且用户另行逐字确认精确
`A3_PROGRAM_BOUNDED` 授权，`advance-until-gate` 才能连续提交机器转换。

## 权威状态

每个 execution root 都拥有独立的：

```text
control_plane/
├── factory.sqlite3
├── driver/
├── ledger/
│   ├── EVENTS.jsonl
│   └── PHASE_TRANSITION_LEDGER.jsonl
└── state/
    ├── PROGRAM_DRIVER_STATE.json
    └── EXECUTION_AUTHORIZATION.json
```

SQLite 是唯一权威 Event Store。事件具有 previous Hash 链，每个事件绑定
结果 State Hash；JSON/JSONL 是可重建且由 `verify-run` 逐字校验的读视图。
Evidence 文件在 State 的 `evidence_index` 中逐文件绑定 SHA256。

## CLI

所有命令默认输出 JSON：

```bash
python3 tools/hfdriver.py status --execution-root /absolute/runtime
python3 tools/hfdriver.py plan-next --execution-root /absolute/runtime
python3 tools/hfdriver.py verify-run --execution-root /absolute/runtime
```

bootstrap 两步：

```bash
python3 tools/hfdriver.py bootstrap-plan \
  --handoff /absolute/EXECUTION_HANDOFF.json \
  --execution-root /absolute/new-runtime > BOOTSTRAP_APPROVAL_BUNDLE.json

python3 tools/hfdriver.py bootstrap-apply \
  --bundle BOOTSTRAP_APPROVAL_BUNDLE.json \
  --confirmation-text 'APPROVE_BOOTSTRAP_BUNDLE::...'
```

独立执行授权使用 `authorization-plan` 和 `authorization-apply`。
Authorization Request 必须精确列出项目/epoch、DAG node、Workpack、解析后
Command Manifest 路径与 Hash、写根、环境、有效期和三个预算。运行时最终
预算取 Automation Profile 与授权请求的较小值。

```bash
python3 tools/hfdriver.py advance-one --execution-root /absolute/runtime
python3 tools/hfdriver.py advance-until-gate --execution-root /absolute/runtime
python3 tools/hfdriver.py resume --execution-root /absolute/runtime
```

`resume` 只恢复已有 Attempt，不创建授权、不重置预算。非幂等命令在
started 后缺少 receipt 时会硬停为 `UNKNOWN_NON_IDEMPOTENT_OUTCOME`。

## Workpack 循环与停机

每次转换依次执行：

```text
validate old state
→ select unique successor
→ authorization intersection
→ reservation + fencing
→ hydrate
→ execute
→ postflight
→ independent review
→ bounded fix/revalidate when needed
→ Evidence Hash
→ promote or hard stop
```

只有 Automation Profile allowlist 中、且确认副作用已清理的临时错误可
自动 retry。Acceptance 失败必须形成 Finding；它不会按普通 retry 处理。
预算耗尽、Hash drift、旧 fencing token、状态歧义、无进展、A→B→A 振荡、
P3 N/A、真实安装、范围扩展、waiver 和未知非幂等结果都会停在一个结构化
hard stop 或 Human Gate，并给出唯一 Return Path。

## 只读迁移

`migration-plan` 只读取旧 candidate 与旧 execution root，将节点分类为
`VERIFIED_COMPLETED`、`REVERIFY_REQUIRED`、`NOT_STARTED` 或
`UNTRUSTED`。`migration-apply` 只接受新的空 execution root，创建新 epoch，
不导入旧授权、不恢复历史 PASS、不执行目标代码或 Workpack：

```bash
python3 tools/hfdriver.py migration-plan \
  --legacy-candidate-root /absolute/old-candidate \
  --legacy-execution-root /absolute/old-runtime \
  --new-execution-root /absolute/new-runtime > MIGRATION_PLAN.json

python3 tools/hfdriver.py migration-apply \
  --plan MIGRATION_PLAN.json \
  --confirmation-text 'APPLY_READ_ONLY_MIGRATION::...'
```

迁移根会停在 fresh bootstrap 门禁。后续使用同一个命令但省略 handoff，
生成绑定现有新 epoch 的审批包；仍需独立精确确认：

```bash
python3 tools/hfdriver.py bootstrap-plan \
  --execution-root /absolute/migrated-runtime > BOOTSTRAP_APPROVAL_BUNDLE.json
```

## 开发验证

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

测试只执行临时目录中的合成 Python 命令，不执行任何真实 Start Package
Workpack。
