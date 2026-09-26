# 通用建设计划接口（首个实现切片）

2026-09-20 路由更新：用户已停止维护旧新建流程。通用 Build 是开发入口和发行包
唯一的新建路线；下文涉及兼容入口的实现记录仅描述历史，不再授予使用旧流程的资格。
旧文档 Review、Freeze、Generate 或委托不能替代新 Build 批准。旧数据只读保留。

状态：`PROPOSAL_CONTRACT_ONLY`。这是通用生产合同的迁移入口，不是完整 Harness
生成器。新增提案持久化与固定版本任务上下文的 Python API；后续的授权、执行与
验收库级切片见[通用控制器](GENERIC_BUILD_RUNTIME.md)，公开路由见[Build CLI](GENERIC_BUILD_CLI.md)。
完整 Harness 与发行验收未完成；搭建文档人工 Review 门禁已接入公开建设入口，
限定 M1 子流程及独立新会话重入已通过，不代表整份 PRD 或发行包验收。
旧兼容生成器不再被此 CLI 导入或调用，但仍存在于开发仓库及历史兼容包中。
独立通用发行组装器只收集通用运行模块，物理上不包含旧专项实现；
公开旧生产入口现已退役；历史源码仍留作回归，不随通用包分发。正式发行验收仍未闭合。

## 搭建文档与人工 Review 统一入口（2026-09-19）

状态：`PROGRAMMATIC_GATE_IMPLEMENTED / SCOPED_M1_ACCEPTED_NOT_RELEASE_ACCEPTANCE`。
用户将入口要求扩展至所有 Harness 搭建需求，不限于 PRD 或 Coding Harness：先落成可供
人工审阅的搭建文档，用户确认后才进入 Foundry。通用提案、来源采集、范围准备/批准/推进
均检查同一 Review 合同；旧 CREATE/authoring 已退役，不追认旧 M1。

```text
自然语言需求 / 问答 / PRD / 项目说明 / 现有工程及变更需求
    → 上游：读取材料、保留需求问答、分析冲突与未决项
    → 输出版本化搭建文档，展示文件及其范围、假设、验收条件
    → 人工 Review：修改 / 拒绝 / 确认实际版本与范围
    → Foundry：以已确认搭建文档生成 Harness 的 Requirement / Plan
    → 具体执行范围与真实运行授权
    → Codex 建设 Harness → 独立验收 → 在 Harness 下实际使用与验证
```

### 上游问答与文档交付

需求问答保留。Agent 可连续读取、分析、查缺、提问和修订草案，无须为内部检查逐步询问
“继续”。没有待问问题，或后台检查全部 PASS，也必须输出文档并停在待人工 Review；
不能从“认为需求已经清楚”直接切换到 Foundry。用户回答澄清问题不等于批准最终文档。

将搭建文档保存为用户可访问的一份或多份可读文件，展示路径/链接、版本和审阅要点，不能
只给内部 JSON、摘要或“已校验无误”的结论。准备和审阅发生在 Foundry 建设入口之前：
此时不创建 Program、Candidate、目标目录或运行目标。默认核心诊断、Foundry 源码工程及
只读历史检查不属于目标搭建，不因此增加人工门禁。

搭建文档不强制大型模板，但最低覆盖：

- Harness 的目标、使用场景、范围与非目标；来源版本、定位与需求映射。
- 输入、输出、功能、关键阶段与依赖、失败返回及恢复要求。
- Codex/Agent 与本地处理的职责边界；允许的工具、读写范围、外部依赖与数据处理限制。
- 交付物、加载/使用方式、独立验收场景、预期结果、必要负例和实际使用验收范围。
- 已确认决定、显式假设、需要用户回答的问题；不把重要缺口默默补成产品事实。

Coding Harness 的搭建文档还应基于完整 PRD 和开发需求，包含功能/状态/流程、数据与接口、
平台/技术限制、既有工程兼容，以及开发、检查和调试需求。其他 Harness 使用适合其目标的
内容，不强加 Coding 或视频专项。原始 PRD/项目材料保留完整追溯角色，不能仅改名便当成
经过推理并可供确认的搭建文档；已有合适文档可以复用，但须展示实际版本并获得确认。

### 搭建质量：最小方案、接口与交付（2026-09-26）

以下是方案推理与实施指引，不增加 IR 必填字段、固定模块、评分表或人工审批：

1. **先分清能力归属。** Codex 提供实际可用的模型执行和工具能力；Foundry 管理输入、
   范围、依赖、独立检查与耐久恢复；项目 Harness 只补本项目的规则、适配和必要本地步骤。
   先复用现有能力，只有确有需求才增加记忆库、路由层或常驻服务。不能让目标接管控制库。
2. **从公开行为反推计划。** 区分用户决定、公开合同与可自主选择的算法/模块组织。
   将完整交付、实际加载/使用、必要失败与恢复场景映射到 Case 和产物；不要把框架目录或
   固定 DAG 当答案。相关原文及全局约束保持可读，摘要不能替代来源。
3. **推演一次实际衔接。** 对相邻生产者/消费者检查参数、数据形状、路径、解释器及读写域。
   运行获准后，优先让一个有效输入穿过必要阶段并被下游实际消费；不以 `--help`、文件存在
   或最小切片通过替代完整交付。实施顺序仍可调整，无额外切片批准。
4. **验证关键机制的行为。** 对当前新增/修改且与需求有关的机制，区分“声明存在”、
   “适用场景实际触发”和“结果达到公开要求”。复用现有检查/运行记录，不做全函数追踪。
   尚未触发的必需能力仍未验证，不因测试没覆盖就删除；无关可选机制无需生成。
5. **按最小责任层修复。** 先问违反谁的承诺、去掉业务细节后是否仍成立、根因在哪里。
   业务/局部适配留在项目；可复现的公共保证缺陷修对应 Foundry 实现，但不因此自动新增
   通用规则。不得为通过检查修改合同或仅放宽 Validator。

实现违约且属于既有写域/预算时，自主修复、复验和推进；机器处理 revision/事件引用，
不让用户复制 Hash 或逐任务说“继续”。合同矛盾、检查基础设施故障、预算/权限失效及
未知副作用按真实边界停顿。目标 Agent 不热修改 Foundry/独立检查器，源码修补另属工程范围。
已有能力正确时补必要覆盖即可；语义设计改进由实际使用检查，不能用提示词字面匹配证明。

交付说明对照原需求给出实际结果、未验证项和限制。`PLAN_CHECKS_ACCEPTED` 只是计划检查
通过，不自动等于完整 Harness 验收。约定交付完成即停止，额外优化进入待办；本次项目
没有约定跨任务复用、性能比较等承诺时，不从开发团队的测试矩阵追加这些义务。

### 人工确认与 Foundry 边界

Review 确认外部合同，不要求用户逐项批准类名、算法和普通工具顺序。实现仍允许 Astra 自主选择。
确认须来自展示文档之后、用户对实际版本和范围的明确决定。Agent 自评、Schema PASS、
问答结束、文档中的 approved=true、旧 PRD/运行批准、代理委托或本政策本身均不是 Review
证明。该上游门禁约束全部通用 Build；旧 Start Package 路线不再可用。代理不能代替用户
确认搭建文档，也不能通过选择旧路由绕过。历史批准与产物不重写、不自动追认为新流程批准。
宿主应记录真实消息引用与被确认内容绑定，复用现有控制存储；不新增数据库、聊天 Hash、
逐需求 SHA-256 或人工复制令牌。完整文档和真实消息引用保存在通用提案事件中；历史 snapshot 不变。
字段验证不认证人类身份，也不证明 IR 与文档在语义上完全一致；可信宿主仍负责核对真实消息、
展示先后及文档到 Requirement 的忠实映射。目标模型不能写控制库。

关键文档内容变化使相关 Review 失效，不能只靠相同版本标签继续。实现内部/Workpack 计划调整
若不改变被确认合同，则不重复要求人工 Review。文档与来源冲突、缺页、验收不可判定时返回
上游修订；Foundry 不自行改写被确认目标。

文档 Review 是内容决定，执行批准是权限决定。充分展示二者后，一条真实回复可明确作出两种决定，
但不能由一个默默推断另一个，不新增逐 Workpack 审批。

`tests/test_build_review.py` 的配对回归覆盖自然语言、问答、PRD、项目说明和既有工程输入；直接输入、未确认草案、
Agent 自批、后台全部 PASS 后直启、通过兼容/委托路线绕过、确认后内容变化均拒绝；真实确认且
内容一致可接入；原始材料可追溯；文档 Review 本身不启动模型/创建目标/授予运行权；历史控制流
可读但不能自动继承到新路径；范围内实现调整不重复 Review。它们是临时样例，不是实际 M1 或发行验收。

### 持久化 Review 形状

通用 `record-build-plan.document_review` 使用以下对象；历史 CREATE 的同形数据只用于追溯：

```json
{
  "document_id": "BUILD-DOCUMENT-ID",
  "version": "v1",
  "documents": [{"source_id": "BUILD-DOCUMENT", "path": "/absolute/displayed-document.md", "text": "完整实际 UTF-8 正文"}],
  "presentation": {"chat_thread_id": "actual-thread", "turn_id": "actual-presentation-turn"},
  "decision": {
    "action": "CONFIRM_BUILD_DOCUMENT",
    "actor": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "actual-thread", "turn_id": "actual-later-human-turn"},
    "user_message": "实际用户确认原文"
  }
}
```

示例不是批准。首次创建前验证对象与完整当前正文；同一用户消息不能换绑另一版本/正文。
通用来源采集还核对 source_id、实际路径和正文；Review 文件须包含在声明来源中。
兼容历史 Program 只通过 `read-history` 查看，不再通过 REOPEN 恢复 authoring。
旧委托不能提供替代 Review；当前通用运行的撤销/未知效果处置不被文档缺失阻止。
文档历史不重写：原文中的草案状态只描述展示时状态，当前决定从控制事件读取。

## 既有只读编译接口

```bash
python3 tools/hffactory.py compile-build-plan --request proposed-plan.json --json
```

只读取 `proposed-plan.json` 并输出 JSON，不读取规范 sibling、初始化 SQLite、
创建输出根或运行任何 `argv`。请求仅有 `requirement_ir`、`plan` 两个字段。
字段格式错误或漏项退出码为 2；成功状态为 `PLAN_COMPILED_NOT_AUTHORIZED`。

## 两个输入

沿用 Requirement IR 的 `program_id`、`target`、`sources`、`atoms`、
`acceptance_cases`、可选 `negative_cases`、`open_questions`、`source_conflicts`。
增加正整数 `revision`，它只是本次声明的版本，不证明持久化批准。

- `target`：`id`、`mission`、非空 `scope`、可为空的 `non_goals`。
- 每个 Source：`source_id`、`path_or_uri`、`loaded_completely=true`。
- 每个 Atom：`atom_id`、`text_or_lossless_paraphrase`、有效 `source_id` 和 `source_locator`。
- 每个 Case：`case_id`、非空 `atom_ids`、`description`。正/负 Case ID 不重名。
- Case 的 `acceptance_contract={source_id, source_locator}` 指向公开验收依据；新范围准备
  必须提供且能解析。旧提案缺少该字段仍可只读/编译，不能因此取得新的执行资格。
  详见[合同与检查器对齐](ACCEPTANCE_CONTRACT_ALIGNMENT.md)，定位通过不证明语义完整。
- 未解决且未显式标记非阻塞的问题或来源冲突会停止编译。

Source 的读取声明和 Case 的描述仍须由需求接入/语义审查核实；结构检查不会
证明材料真的读完，也不会证明目标明确。旧 IR 中的其他需求上下文不被改写，
但不作为运行授权使用。不需要在该入口补旧 lock、epoch 或 SHA-256。

Plan 的字段如下，未声明的结构字段会被拒绝，避免静默忽略授权或旧专项控制项：

| 对象 | 字段 |
|---|---|
| Plan | `schema_version="1.0"`, `plan_id`, `revision`, `requirement_revision`, `workpacks` |
| Workpack | `workpack_id`, `job_id`, `executor`, `goal`, `depends_on`, `atom_ids`, `inputs`, `artifacts`, `verification`；LOCAL 可选 `local_argv` |
| Input | `kind="SOURCE"` 或 `"ARTIFACT"`, `id` |
| Artifact | `artifact_id`, `path`，可选 `replaces_artifact_id` |
| Verification | `case_id`, `argv`, `artifact_ids` |

`executor` 只表示 `CODEX` 或 `LOCAL` 的计划角色，不绑定模型、进程、工具权限或
执行权限。`verification.argv` 是供后续独立验证角色运行的命令数组；编译时不执行，
也不认定命令真的证明该 Case。`LOCAL` 可声明非空字符串数组 `local_argv`，首项
由执行范围绑定到真实程序；静态声明本身不授予任何读写或进程权限。当前计划
不得作为可运行请求。所有相对文件路径将来仍须在实际根目录中检查链接和写域。

ID 使用字母/数字开头，允许字母、数字、点、下划线和连字符，最多 128 字符。
任务名称、Job 数量、阶段与依赖均由当前需求决定，没有固定行业枚举或项目布局。
Artifact 是文件，路径必须规范相对、不越界、不形成文件/目录冲突，也不能占用 Git
或 Foundry 控制库。每个产物 ID 唯一归属一个 Workpack/Job，跨 Job 读取须显式声明为
Artifact 输入，且其生产者必须是已声明的直接或传递前置任务。

同一源文件可以由后续任务修改：使用新的产物 ID，并用 `replaces_artifact_id` 指向
同路径的前一版本；前一版本必须是本任务声明消费的前置产物。每条文件版本链只能有
一个初始版本，不能从同一版本分叉为两个写入者。读取旧版本的其他任务必须先于替换
任务完成，或者改为读取新版本；不能依赖共享路径保存已经覆盖的旧字节。这只是计划
层的顺序约束；库级控制器已接通调度、产物身份与原位修复，真实 Codex 编辑和历史
文件快照消费并未因此完成。

每个需求、每个已声明 Case、每个任务的输出都必须有对应验证声明。可达性和
覆盖检查不替代行为验证。多任务可以分别覆盖同一需求，但每个任务均承担自己的
验证义务。未声明负例时不自动扩展一套攻防矩阵。

## 输出与后续消费边界

输出携带原 Plan 的独立副本、`requirement_binding`、`artifact_index` 和
`requirement_coverage`。独立静态校验器检查输出没有丢失、增添或改绑任务、产物
与需求；它不调用 Producer 重建“正确答案”，也不修复错误输出。

没有消息摘要、产物摘要、回执摘要或新的状态库。内部实施变化可提高 Plan
revision 而保留 Requirement revision；是否属于合法实施变化仍需后续控制器
根据已批准范围判定，不能靠修改数字取得权限。Requirement 实际变化必须绑定新
版本，不能以此接口绕过旧生命周期或重用旧授权。

W2/W3/W5A 的库级消费者与公开宿主入口已接通，真实模型限定子流程已验收，完整发行未验收。只读编译和
提案上下文的 `authority_validated`、`behavior_verified`、`writes_performed`、
`execution_started` 仍全部为 false，不能借下游接口把提案标成已执行。本切片不改变旧链
的 authority/event Hash，不授予后继能力，不宣称完整 PRD 适配或发行验收。

## 提案事务与任务上下文（Python API）

`build_authoring.py` 提供 `record_build_plan_proposal`、`read_build_plan_proposal`、
`read_build_task_context`。它们只支持 `revision_store.RevisionControlEventStore` 的既有 `REVISION_V1` 格式。
源码兼容 API `ControlEventStore(storage_format="REVISION_V1")` 转到同一实现，
不改数据库格式、不复制状态；通用包不包含旧 Hash Store。记录接口只可用于已经允许的本地提案写入；
[公开建设入口](GENERIC_BUILD_CLI.md)另行准备并记录真实范围批准，提案本身不授权执行。

- 一个控制库拥有一个 Program；新提案的 Requirement 与 Plan revision 从 1 开始。
- 新提案按预期 stream revision 在 `BEGIN IMMEDIATE` 事务中比较并写入。并发变化
  返回 `STATE_REVISION_CONFLICT`，不覆盖另一调用者的修改。
- Plan 可按下一 revision 改进实施而保持 Requirement 不变；同一 Requirement
  revision 的内容必须完全相同。Requirement 内容变化须显式增加 revision，仍是
  未批准提案，不会继承运行权限。
- 使用原始规范 JSON 比较幂等请求，事件 ID 使用随机 UUID，不计算消息/事件/回执
  摘要。相同请求重试返回原事件；`require_new` 不允许凭重试结果再次派发副作用。
- 任务上下文引用指定提案事件，包含该任务需求、相关 Source、Case 与验证声明、
  产物输入归属，并保留全局需求上下文；不从“最新 JSON 文件”隐式选版本。
- `REVISION_V1` 与历史 `LEGACY_HASH_V1` 不自动迁移、不混用；旧运行控制器拒绝将
  提案库解释为旧运行授权。测试仅使用临时数据库，不写历史 Program 或 Candidate。

数据仍只落在同一类控制库的事件表和幂等表，没有第二套权威快照。`verify_stream`
在新格式中只检查版本连续性，明确返回 `content_integrity_verified=false`；事务与
版本检查不是反篡改认证，更不证明业务质量。运行消费者的 H2 核对只覆盖指定的
verifier/产物文件；参见通用控制器说明，不对本提案链新增摘要。
只读编译的 `writes_performed=false` 不描述提案记录 API：后者确实写入控制库，
但不创建目标目录、不运行任务、不批准 Harness。
