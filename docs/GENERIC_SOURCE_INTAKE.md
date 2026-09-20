# 通用本地来源接入（完整文本切片）

状态：`LOCAL_SOURCE_INTAKE_ONLY`。此接口读取显式清单中的完整文本，供通用需求提案
绑定来源。它不证明 PRD 语义完整、不自动生成需求、不解决歧义、不授予建设权限。

所有目标搭建仍先遵守[统一搭建文档入口](GENERIC_BUILD_PLAN.md)：保留问答、输出文档、
由用户实际 Review 并确认，之后才进入 Foundry。读取成功或内部校验 PASS 不能代替该决定；
本底层读取接口不实现新的人工 Review 程序门禁。

## Python 接口

`harness_foundry_factory.source_intake` 提供三个接口：

```python
snapshot = load_local_sources(source_root, [
    {"source_id": "PROJECT-BRIEF", "path": "requirements/brief.md"},
    {"source_id": "DATA-RULES", "path": "requirements/data.json"},
])
validate_requirement_source_bindings(requirement_ir, snapshot)
text = resolve_source_locator(snapshot, "PROJECT-BRIEF", "L2-L4")
```

`source_root` 是调用者显式选定的本地只读材料根；每条清单必须且只能包含
`source_id` 和 `path`。`path` 是规范相对 POSIX 文件路径，不能绝对、包含 `..`、
反斜杠、URL 或无效控制字符。符号链接只能解析到该材料根内的普通文件。
返回快照不包含机器绝对路径；绑定使用 ID 和完整内容，不计算 Hash。

支持 UTF-8 的 `.md`、`.markdown`、`.txt`、`.json`。JSON 必须可完整解析，但保留
原始文本而非重排后的对象。文本不截断，保留原始换行符。空纯文本可完整读取，
但没有可以引用的行；空 JSON 会报告解析错误。未支持的 PDF、DOCX、图片等必须
明确返回 `SOURCE_FORMAT_UNSUPPORTED`，不会冒充已完成视觉或文档解析。

附件必须逐项列入清单。清单中的缺失附件、无法读取文件、无效 UTF-8、无效 JSON、
越界路径都中止本次读取并报告原因与对应 Source；不返回部分成功快照，也不
静默省略附件。接口不会自动爬取 Markdown 链接或联网。因此，未列入清单的附件
是否遗漏，仍需要材料清单核对；不能把“所有显式条目读取成功”当作“全部需求
资料已经齐全”。

## 快照与定位

快照是可序列化 JSON 对象：`schema_version="1.0"`、`sources`，以及固定为 false
的 `semantic_completeness_verified` 和 `instructions_executed`。每个 Source 包含：

- `source_id`、`path_or_uri`（本接口为清单内的相对路径）。
- `loaded_completely=true`、`format`（`MARKDOWN`／`TEXT`／`JSON`）。
- `text`（全文）、`line_count`（按文本实际行计算）。

定位只接受从 1 开始的 `L2` 或闭区间 `L2-L4`，返回包含原换行符的对应文本。
不猜测 Markdown 标题锚点、不将 JSON 指针等未实现格式当作有效定位。定位针对
传入的快照，不重新读取可能已变化的原文件。

`validate_requirement_source_bindings` 是纯函数：确认 Requirement 的来源清单
与快照逐一匹配且没有丢掉显式附件，并确认每个 Atom 的 `source_id` 与
`source_locator` 可解析。它不检查文字改写是否忠实、不证明每项真实需求都已有
Atom，也不判断材料间冲突已解决。这些是后续语义审查责任。

## 状态与授权边界

来源中的命令、提示词和权限宣称一律作为文本保留，不执行、不改变 Foundry
规则，也不触发工具调用。这个模块不写任何数据库或文件；上层可把完整快照和
指定提案版本一起写入既有 Revision ControlEventStore，而不是另建状态库。

重新读取后的全文身份比较、权限绑定和运行时来源变更失效，由上层控制器负责。
结构有效的快照本身不是文件真实性、用户批准、语义验收或 Harness 可用性的证明。
