# 按需查询与采用知识

WP04 提供本地知识文件、条件查询和采用记录。适合在任务出现明确知识缺口时查找资料、方法、能力引用或失败反例。它不运行条目中的命令、不安装工具、不调用模型，也不把知识声明变成产品验收或运行授权。没有命中时可继续原来的可行路径，不要求每项任务都查询。

入口 `tools/rsi_wiki.py` 已纳入 WP05 运行包和可选交付材料；使用 [交付指南](RSI_DELIVERY.md) 将依赖、知识和说明一并交给目标 Harness。包内调用与真实新会话使用分开验收；不能只复制一个脚本或凭准备成功声称 G05/G08 完成。

## 如何接入

配置文件显式列出要查询的集合。`path` 相对于配置文件位置解析；项目私有集合也可以使用明确的绝对路径，但可交付场景优先用相对位置。不会自动扫描其他项目或开发者目录。

```json
{
  "collections": [
    {"id": "public", "path": "knowledge/public", "version": "1", "visibility": "PUBLIC"},
    {"id": "project", "path": "knowledge/project", "version": "2", "visibility": "PROJECT"}
  ]
}
```

每个集合中的 `collection.json` 声明版本及文件：

```json
{"version": "1", "entries": ["decimal-v1.json"], "updates": []}
```

配置版本与集合版本不符时返回具体缺口，不自动选择最新版。文件只在各自集合根目录内读取；共享来源可作为已声明集合的材料准备，不隐式跟随越界链接。缺少一个集合或条目时，其他可读条目继续返回，缺口保存在 `diagnostics`。

`PUBLIC`／`PROJECT` 是来源归属，不是匿名化结果或权限机制。工具不会将项目条目写回公共集合，也不会自动将查询报告放入发行包。查询和采用报告可能带有项目说明，按原材料权限保存。公共包只纳入已筛选的公开材料；私有预期、凭据、个人路径和保密资料仍留在项目位置。不要将私人原始日志直接当作公共条目。

## 条目与证据

下面是字段示意，摘要应由实际来源文件计算；不能使用占位摘要声明通过。

```json
{
  "id": "decimal-calculation", "version": "1",
  "title": "精确小数计算", "summary": "在所列条件下使用十进制计算。",
  "kind": "METHOD", "state": "CANDIDATE",
  "keywords": ["decimal", "金额"],
  "conditions": {"python": ["3.14"]}, "excludes": {"input": ["binary-float"]},
  "sources": [{"path": "evidence/local-check.json", "version": "check-v1",
               "sha256": "实际64位摘要", "evidence_kind": "DEVELOPMENT_GREEN", "ref": "/cycles/0"}],
  "limits": ["只保留开发检查结果，不代表所有环境适用。"],
  "pending_checks": ["所需设备上的实际验证"],
  "capability_refs": ["所选能力包及版本"]
}
```

- `kind` 为 `FACT`、`METHOD`、`CAPABILITY_REFERENCE` 或 `COUNTEREXAMPLE`。原始失败可作为反例，不当作成功方法。
- `state` 为 `CANDIDATE`、`VERIFIED_SCOPED`、`SUPERSEDED` 或 `WITHDRAWN`。声明 `VERIFIED_SCOPED` 必须填写 `validation_scope`，说明只在哪个范围验证；工具仍返回 `independently_verified: false`。
- `sources` 可引用 WP01 案例报告、WP03 红绿报告或其他可靠材料。版本和类别由材料提供者声明，文件摘要核对只证明来源字节一致，不能证明内容正确。可选 `ref` 等细节原样保留，不冒称工具已作语义核实。
- 缺来源、来源不可读或已变化、条件未知／不符、明确不适用、待验证及生命周期缺口都会返回限制；不会用其他条目的 PASS 补齐。
- `conditions`／`excludes` 是简单的字符串精确匹配，不解析版本范围，也不替代语义评估。更复杂适用条件写在说明中，由调用者核对。第一版是确定性的关键词检索，中文用相邻二字片段匹配；不是语义搜索，没有命中不表示相关知识不存在。

新经验由现有案例、结果和维护者分析形成候选文件，不自动把模型总结或 GREEN 提升为已验证方法。保存候选：

```sh
/path/to/project/.venv/bin/python -B tools/rsi_wiki.py propose \
  --entry proposed-entry.json --output knowledge/project/new-method-v1.json
```

`propose` 将状态写为 `CANDIDATE`，输出必须是新文件。核实后在对应维护位置另存已验证版本及其范围，更新集合声明；不是新增审批，也不修改源案例或预算。

## 查询与采用

```sh
/path/to/project/.venv/bin/python -B tools/rsi_wiki.py query \
  --config wiki-config.json --question '当前金额计算如何避免二进制误差' \
  --conditions '{"python":"3.14","input":"decimal-string"}' \
  --output query-001.json
```

默认最多返回5项，可用 `--limit` 调整。先在关键词相关条目中按声明条件排序：必要条件无缺失且无已知冲突 → 必要条件未知 → 已知不符或明确排除；同组再按关键词分数及原稳定身份顺序排序，最后截断。已知冲突与未知同时存在时按冲突组处理，但两类说明都保留。没有声明条件只表示没有已知条件冲突，不证明方法适用或更可信。此排序不增加硬性过滤，未知、不适用、反例和撤回条目仍可返回并保留原说明；`matched_total` 仍统计截断前全部相关条目，无符合条件项不阻断任务。结果保留集合和条目版本、条目字节摘要、来源实际摘要、完整限制及能力引用；相同条目ID在不同集合中分别保留，不互相覆盖。命令只写指定的新报告，不执行查询内容。

调用者核对来源、版本和适用条件后，可以记录采用或不采用理由：

```json
[{"collection":"project","id":"method-id","version":"1",
  "sha256":"查询返回的entry_sha256", "action":"ADOPT",
  "reason":"符合本任务的已核实条件；任务结果仍交独立检查。"}]
```

```sh
/path/to/project/.venv/bin/python -B tools/rsi_wiki.py record \
  --query query-001.json --decisions decisions.json --output adoption-001.json
```

`action` 可为 `ADOPT` 或 `NOT_ADOPT`。无命中时可记录空列表，未采用不阻断任务。每项决定必须对应查询中一个确切的集合、条目版本和摘要。收据固定当时读到的内容、来源、限制及理由，后来更新集合不会改绑旧收据。记录采用只是调用者的决定，不是工具已授权、知识已独立确认或任务已验收；即使选择有限采用，也保留全部限制。任务结果仍使用已声明的独立检查。

## 反证、替代与旧依据

后续发现反证时，另存生命周期说明，不改旧条目。将说明文件列入新集合版本的 `updates`；更新查询配置时明确选择该版本。

```json
{
  "entry_id":"method-id", "entry_version":"1", "entry_sha256":"旧条目实际摘要",
  "state":"WITHDRAWN", "reason":"新证据否定原结论",
  "sources":[{"path":"evidence/counterexample.json", "version":"counter-v1",
              "sha256":"实际摘要", "evidence_kind":"COUNTEREXAMPLE"}]
}
```

可用 `SUPERSEDED` 表示替代，并附新版引用。查询按目标身份和字节关联，不把同ID的其他版本误撤回。有效的撤回说明不会因反证文件暂时不可读而消失，同时明确反证暂不可核实。说明缺失或目标摘要不符会显示未解决限制，不能默认为结论仍然充分。

旧查询、采用记录及历史运行继续保存当时依据；当前状态要重新查询所选集合版本，不能把旧查询当作“截至现在仍有效”的证明。撤回不抹去历史预算或外部效果；涉及运行权限的变化仍由现有授权机制负责。

## 对照、依赖及验收范围

A/B 对照分别复制或固定知识目录及配置，只查询各自声明的集合，不把候选总结写进基线。工具不作隐式写回，也不自动跨集合合并知识；调用者若显式配置同一个可变目录，仍需在对照准备中冻结它，不能宣称物理隔离。

源码入口依赖 `rsi_wiki`、`rsi_cases`、`rsi_review`、`build_types` 和 `python_startup`，无新增第三方依赖。工程测试会把这些文件放入新目录，以 `-I -B` 启动查询，验证必要支持文件没有借用开发目录。此项是源码隔离检查，不是固定 ZIP 或生成 Harness 的交付验收。后续 WP05 应把这些入口与配置正确交付，并由 G05/G08 用新会话、新任务和独立预期验证实际效果。
