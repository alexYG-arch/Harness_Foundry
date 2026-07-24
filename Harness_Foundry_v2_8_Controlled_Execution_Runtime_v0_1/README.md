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

Driver materialization 会把当前标准库 Runtime 源码复制到 execution root，
使用隔离 Python 入口启动，并在关闭 runtime verification 节点前真实执行
一次只读 `status` 探针。仅存在 launcher 文件或 Hash 不等于 Driver
可运行。

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

在申请 A3 前，Runtime 内置的通用 Resolver 可以把一个 provider profile
展开为所选 DAG 节点中每个 Workpack 的 Hash 绑定 Command Manifest。
profile 使用 `{{HF_EXECUTION_ROOT}}`、`{{HF_CANDIDATE_ROOT}}`、
`{{HF_NODE_ID}}`、`{{HF_WORKPACK_ID}}` 和 `{{HF_WORKPACK_REF}}` 占位符，
不需要逐 Workpack 手工登记：

```bash
python3 tools/hfdriver.py resolve-overlays \
  --execution-root /absolute/runtime \
  --bundle /absolute/WORKPACK_AUTOMATION_RESOLVER_BUNDLE.json
```

Runtime 会校验 Program/epoch/candidate 绑定、Workpack 顺序、环境、绝对
executable 和最终 Hash、argv、cwd、读根、写根、postflight 和独立 review，
再把不可变 Manifest 登记到 SQLite 和 Evidence Index。每条命令必须显式
声明 `allowed_read_roots`；Runtime 会校验它只能落在候选只读范围、节点写根、
Evidence、Driver runtime/provider 或只读迁移快照中，并以保留环境变量把
读写交集传给受控 Provider。已有外部 Resolver
也可以直接登记解析完成的 overlay：

```bash
python3 tools/hfdriver.py register-overlays \
  --execution-root /absolute/runtime \
  --bundle /absolute/RESOLVED_COMMAND_OVERLAY_BUNDLE.json
```

Resolver 和 Overlay 注册都不运行命令、不激活 Workpack，也不授予执行权限。
后续
`authorization-plan` 只能引用已登记的精确路径和 Hash；修改 overlay
需要在没有 Active Authorization 时产生新的登记事件。

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

每个 DAG 节点严格按声明顺序逐个推进 Workpack；每个 Workpack 依次执行：

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
→ promote Workpack
```

只有 Automation Profile allowlist 中、且确认副作用已清理的临时错误可
自动 retry。Acceptance 失败必须形成 Finding；它不会按普通 retry 处理。
Fix 命令必须同时声明 `{{HF_FINDING_REF}}` 与
`{{HF_FINDING_SHA256}}`，Runtime 在执行前绑定本轮 Finding，修复后重新
postflight 和 Review。Review 必须使用与 execute/fix 不同的
`executor_identity`、声明 `READ_ONLY` 和空写根；Runtime 还会比较 Review
前后的目标写范围 Hash，防止“声明只读、实际写入”。

`max_loop_rounds` 约束单个 Active Workpack 的 retry/fix 循环。Workpack
成功 promotion 后，下一 Workpack 获得同一授权声明的完整循环额度；运行态
同时保留 `loop_rounds_used` 累计审计计数，以及
`active_workpack_loop_rounds_used` 当前 Workpack 预算计数。旧 epoch 的
Finding 和 hard stop 只作为迁移审计输入；当前 epoch 的 SQLite 状态和
Evidence 才是 predecessor closure 与 active blocker 的权威来源。自动化
命令 Profile 应把当前 `control_plane/state` 声明为只读根。

内置 `codex_workpack_provider` 不使用旧的 `--sandbox` 模式。它忽略个人
Codex config/rules，使用 Hash 可审计的 Custom Permissions Profile：
`:minimal` 只读、候选和声明读根只读、workspace/evidence 写入、工具网络
关闭，并显式拒绝用户 `~/.codex` 与 workspace `.codex`。Provider 只把当前
Hash 绑定的运行时 Python 标准库前缀额外加入只读范围，并把解释器复制为
临时、只读、调用前后 Hash 复验的执行投影；实现与 Review 测试使用该投影，
不会给 Homebrew 或其他外部安装根写权限。当前独立 Review 可通过直接复验
清除旧 Review Finding，不要求预先存在另一次成功 Review。因此个人 Memory
和项目私有配置不会进入 Workpack 子 Agent 的可读范围。Provider 的 Profile
Hash 与解释器投影 Hash 会写入命令 stderr，并随 Runtime receipt 进入
Evidence 链。

Workpack 成功后 Runtime 自动推进下一个 Workpack 和下一个已授权 DAG
节点，不再逐节点请求确认。正常人工门禁只保留预算/修复次数耗尽、授权
范围变化、P3 N/A、范围扩展/waiver 和真实目标安装；Hash drift、旧
fencing token、状态歧义、无进展、A→B→A 振荡及未知非幂等结果仍作为
安全 hard stop。

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
