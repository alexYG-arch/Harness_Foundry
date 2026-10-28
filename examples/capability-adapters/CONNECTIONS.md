# 外接能力连接与自动加载（E1）

此入口将选定的本地外部包登记到项目或 Foundry 实例。启动设计时自动读取适用连接、能力目录和声明的基础材料；相关 Skill 按任务需要展开。不需要在 Chat 中声明组织名。它只准备公开材料，不执行插件、安装、初始化、登录、Git、更新、上报或 RSI 修复。

使用实际绑定的 Python 3.11+ 解释器运行 `examples/capability-adapters/connections.py`。`INSTANCE` 是用户明确选择的 Foundry 实例目录，`PROJECT` 是已有项目；无项目时省略 `--project-root`，不提前创建目标。

```bash
"$PYTHON" "$INSTANCE/examples/capability-adapters/connections.py" connect \
  --root "$INSTANCE" --scope instance --id vendor --source /selected/plugin.zip
"$PYTHON" "$INSTANCE/examples/capability-adapters/connections.py" load \
  --instance-root "$INSTANCE" --project-root "$PROJECT"
```

项目级连接改为 `--root "$PROJECT" --scope project`。连接只读取选定目录或 ZIP，支持原生 `.codex-plugin/plugin.json`（单一 `skills` 目录）与已有 `capability.json`。ZIP 可以有一个外层目录，不解压、不安装。清单声明的 Skill 目录必须在 ZIP 中实际存在：显式空目录或其下成员均可；没有 Skill 的合法目录仍可加载。目录缺失会保留具体诊断，首次连接失败不替换旧登记，加载时其他连接的已知结果保留。未声明 Skill 目录的包不因此新增要求。分发地址需先按原授权取得本地副本；其他原生格式、编译或改写由 E5 接续，不假装已支持。

记录存于所选 root 的 `.foundry/connections.json`。同一连接、同一来源重复连接不增加修订；明确重连改变版本或材料时追加记录，保留旧版。`disconnect --root … --scope … --id …` 追加停用状态，只取消后续自动加载，不卸载插件、不更改原插件启停、不撤销远端副作用。登记写入串行化；写锁存在时报告占用，不猜测进程状态或自行清除别人的锁。

加载结果区分 `READY`（目录/材料准备就绪）、`model_load_verified=false` 与 `runtime_verified=false`。没有连接时返回空结果且不创建文件；来源暂不可读或内容变化时保留其他已知提供方和诊断，不偷偷更新绑定。相同提供方多份连接报告冲突，需选择实际绑定，不静默覆盖；不同提供方的同名 Skill 使用 `instance.<连接ID>:<Skill名>` 或 `project.<连接ID>:<Skill名>` 区分。

```bash
"$PYTHON" "$INSTANCE/examples/capability-adapters/connections.py" load \
  --instance-root "$INSTANCE" --project-root "$PROJECT" --skill instance.vendor:review
```

目录中的 Skill 说明用于选择；完整正文只有选中时返回。原生包未声明基础规则时不猜测所有 Markdown 都是规则。已知公开基础材料可在连接时重复指定 `--base-material package/relative.md`；已有能力包沿用 `materials`。项目原有 AGENTS/规则仍按宿主原有入口读取，连接工具不代替原插件的启停或规则路由。后续 E3 应先核对原配置，再衔接初始化、更新及禁用；E1 不把连接当作项目已启用，也不依据 Skill 的执行文字启动任何原生动作。发现的 Skill 是待采用的资料，不产生运行授权。

## 衔接现有材料准备

`prepare.py` 的可选 `connections` 配置复用同一加载器。现有选版、环境及检查依赖不变；外接目录不整体加入进程可读域，工具调用留给 E2。示意配置如下，其中所有路径由实际项目填写：

```json
{
  "project_root": "/selected/project",
  "connections": {
    "instance_root": "/selected/foundry",
    "skills": ["instance.vendor:review"],
    "workpack_ids": ["IMPLEMENT"]
  }
}
```

可与原 `base_materials`、`source_root`、`selections`、`environment_bindings` 合并，也可仅准备外接公开资料。目录与加载正文进入原 `source_manifest`、Requirement SOURCE 和选定 Workpack 输入；不要把完整宿主材料给模型。私有检查依赖仍沿原保护入口。`check_selection` 核对已准备的外接源，不根据后来断连去回改历史绑定；来源变化需新材料及原适用版本交接，不能继续使用旧摘要。

这不是每任务必须调用的接口：无连接继续原路径；已经加载、同版且适用的材料沿用真实读取记录。生成材料只能证明宿主读取/准备，模型实际收到并使用需要独立的模型取证，不能从 `loaded_completely` 的来源记录推导完成。

## 交付与 RSI 接续

连接目录或 ZIP 后，能力名称、Skill 路径和版本来自原描述及正文。自动加载目录与基础资料不等于安装、初始化或运行所有功能；所选 Skill 保留原相对引用，目标交付使用 [EXTERNAL_DELIVERY.md](EXTERNAL_DELIVERY.md) 的完整依赖交接。

RSI 继续由现有 `tools/prepare_rsi_delivery.py`、`import_rsi_case.py`、`rsi_wiki.py`、`rsi_review.py`、`report_rsi_tdd.py`、`report_rsi_adoption.py` 负责。连接外包不自动选中 RSI，选择 RSI 不要求外包；所选任务在已有外层修复交回点接入，不新增控制器、预算或验收权威。见 [RSI_HANDOFF.md](RSI_HANDOFF.md)。

原生调用通过显式适配器接入，见 [NATIVE.md](NATIVE.md)。提供方仍负责原鉴权、启停、上报和更新行为；本版不自带任何具体第三方提供方适配器。真实服务与交付验收分别记录。
