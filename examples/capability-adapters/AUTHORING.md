# 外接能力作者入口

`author.py` 将选定来源转换为既有 `connections.py`／`native.py` 可读取的独立候选。原包不改写，准备不执行其中的命令，也不注册项目或消耗生产尝试。符合原接口的包直接用原入口，无需再转换。

## 输入与操作

用任务绑定的 Python >=3.11 调用：

```sh
"$PY" -I -B examples/capability-adapters/author.py \
  --request /declared/author/request.json \
  --source-root /declared/original \
  --output /declared/candidate-v1
```

输出必须是原包之外的独立目录。相同输入、声明和生成器再次指向完整同一输出时只核对并取回；不同或不完整输出保留，改用新目录，不覆盖旧版。

请求示例：

```json
{
  "descriptor":"toolbox.json", "format":"json", "adapter_version":"1",
  "runtime_files":["lib/*", "guide.md"], "materials":["guide.md"],
  "mapping":{
    "provider":{"$pointer":"/package/id"},
    "version":{"$pointer":"/package/release"},
    "license":{"$pointer":"/package/license"},
    "operations":{
      "sum":{
        "argv":["tool:python", "package:lib/cli.py"],
        "tools":["python"], "effects":[],
        "requirements":["原 CLI 的十进制参数"]
      }
    }
  },
  "changes":[], "build":{}
}
```

JSON/TOML 用 `$pointer` 读取实际字段；数组位置使用从 0 开始、无前导零的十进制索引，字典键与 `~0`／`~1` 转义保持原语义；其他字面值是作者声明，不能冒称来自原包。原始描述文件和字段位置、未映射值、实际输入摘要、生成器及适配器版本均另存。未知更新、认证、副作用字段不默默删掉；不完整操作留在报告，不生成可调用入口，其他完整操作仍可准备。

TOML 日期、时间及非有限浮点数在分析报告中以字符串和 `report_scalar_types` 的路径／原类型共同保存；原描述字节仍由 `source-descriptor.bin` 保留。不将这些报告展示值自动转换为运行字段或授权。

`text` 模式保留 YAML、README 或其他 UTF-8 原文，并使用作者明确给出的映射。**它不是 YAML 语义解析器，也不自动从自然语言推断命令。** 完整 YAML 自动转换、任意格式编译及任意业务自动改写不在本入口的已实现范围。有明确转换器时可先在原授权工程流程中形成 JSON/TOML 候选，保留原件、转换版本与差异，再使用此入口。

`runtime_files` 显式选择运行所需文件，`materials` 是其中获准给生产者读取的公开说明。原文件保持相对布局，放在 `package/upstream/`；普通文件权限和已同时选择目标的包内相对文件链接保留。多层文件链接逐层核对直接目标，必须携带中间链接；合法的 `./`、`../` 包内相对目标保持原样。 对 `spare/../tool.py` 等路径，保留实际经过的必要普通目录，并在报告 `runtime_directories` 中列明；不复制目录中的未选内容，不据此声称完整目录权限交付。生成和取回均核对链接可解析、目标仍在包内且内容匹配选定输入；缺目录或断链时保留旧候选并报缺口，不自动修补或重放。路径经过目录软链接时需显式派生布局，不能按普通目录悄悄展开。绝对链接或未随选目标需作者明确处理为派生布局，不能悄悄借开发目录。任意目录链接、跨设备安装器、第三方依赖安装等仍按 E6 的目标交付范围验证。

## 接入与真实运行

1. `package/` 含生成的 `capability.json` 和选定原始运行文件。用已有 `connections.py connect --source .../package` 连接；以后设计自动读取所选材料，不依赖项目关键词。
2. 原 `prepare.py` 的 `connections.native` 指定该连接 key、`root=.../package`、`adapter_path=.../adapter.json`、所选 operations 和各工具的 `environment_bindings`。原 `consume.py`／`native.prepare_call` 继续检查实际版本及工具，再形成 argv。
3. `tool:角色` 使用显式绑定的宿主工具；`package:相对路径` 在候选内定位。参数按 argv 元素传递，不串成 shell 命令。原退出、stdout/stderr、认证、更新和副作用由原工具及原执行链负责。
4. 运行前沿已有授权、权限、预算和 `CommandObservation`；实际调用可用 `attach_call` 关联。完整回执用 `recover_call` 取回，不重新转换、编译、初始化或重放原操作。准备成功及退出0都不代表业务接受。

`mapping-report.json` 和 `source-descriptor.bin` 属于作者分析材料，可能包含私有元数据；不自动给 Worker、公共知识或目标交付。候选 `package/` 和 `adapter.json` 也只交付经过选择的内容。名称、PUBLIC 声明及摘要不代替许可、脱敏或独立检查。

## 编译与包装／改写

`build` 和 `changes` 保留作者关于工具链、依赖、输出及差异的说明，本入口不执行它们。编译可以作为原生 adapter 的独立操作，实际编译由原宿主在隔离输出目录、声明工具和预算中执行；编译后选取实际产物、绑定新候选，再做真实运行及独立行为检查。不得把一次主机编译当作跨平台可复现。

必要包装或改写代码另存候选并列入 `changes`，保留原实现及公开合同。正常、错误及合法等价输入的预期由原合同独立提供；未知行为留待验。无必要不改写外接包，也不改变自动上报、Git依赖和更新行为。工具只转换声明，不保证任意程序语义等价。

工程样例使用独立的十进制 CLI/清单结构，以及 C 编译＋JSON 包装：按既有连接、原生调用和报告取回验证，不修改 Foundry 核心。此类样例属于 T13–T15 的工程证据，不能关闭真实模型、外部服务和目标新会话 T16/T17，亦不改变原验收分母。

## 功能级接入 v2 工程候选

本分支的 ALL / ON_DEMAND、决定复用、内外混用交付、接收绑定及报告入口见 [功能接入说明](FEATURES.md)。旧输入与旧包保留原语义；新版本和适用验证分列，不把候选材料记为部署或服务通过。
