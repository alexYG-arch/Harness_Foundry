# 选择功能、交付及升级

本预发布提供描述 v2 的通用接入机制。旧描述和未使用新字段的配置继续走旧入口。连接负责发现材料，功能选择负责说明本次用途；两者都不执行初始化、上报、Git 操作或模型任务。

## 选择本次需要的功能

`prepare.py --config CONFIG --output NEW_HOST_DIRECTORY` 沿用原接口。在选项中增加 `integration_mode`：`ALL` 为所有功能登记形态，构建期资料保持 `BUILD_ONLY`；`ON_DEMAND` 根据捕获需求的来源、行号和必要依赖选入，缺省采用此模式。准备结果 `READY` 只说明材料齐备。

```json
{
  "project_root": "/absolute/project",
  "integration_mode": "ON_DEMAND",
  "selections": [{"directory": "/selected/text-count/2", "version": "2", "workpack_ids": ["MAKE"]}],
  "requirement_links": [{"capability": "text-count", "feature": "count-text", "source_id": "BRIEF", "source_locator": "L1-L3"}],
  "environment_bindings": {"python": {"path": "/project/.venv/bin/python", "observed_version": "3.14.5"}}
}
```

该片段合入原项目配置：BRIEF 必须是 `source_manifest` / `base_materials.request.requirement_ir.sources` 中实际捕获的来源。工具核对字节及定位，外层 Codex 判断语义。`inventory.py --materials .../materials.json --markdown` 只读显示选入、依赖、未选及构建期材料。功能拥有的文件和实际调用的 `entry.tool` / `tool_refs` 分开计算；共享文件不会自动加入未选工具或其环境。

## 需求和能力冲突

标签提示宿主核对实际条件，不据标签自动要求批准。已授权范围内的路径适配及确定性合并直接沿原机制；只有原规则要求用户决定的未决取舍，宿主才在配置的 `capability_conditions` 填入具体条件：

```json
{"capability":"example","feature":"report","unresolved":true,"category":"PROJECT_CONFLICT","question":"Which conflicting behavior should be retained?","evidence":["actual captured requirement and provider behavior references"],"options":[{"id":"AS_IS"},{"id":"POST_DELIVERY"}]}
```

第一次准备返回 `decision_requests`；真实决定沿计划的 `decision_records` 关联 request ID、context identity、消息引用及 choice。不要生成虚假用户消息。请求身份只取相关描述、需求、依赖和提议，不取写入后的状态或时间；相同决定可复用，相关输入变化需重新核对。`feature_pins` 用实际决定 ID 绑定形态；描述为 build 的功能保持 `BUILD_ONLY`。这些都是原合同的材料，不是第二套运行授权。

依赖按决定后的最终形态核对：交付后运行的功能不能依赖最终为 `BUILD_ONLY` 的功能，即使该依赖原先标为 `runtime`／`both`；搭建期功能仍可依赖搭建期功能。保留正常的 `AS_IS`／`BRIDGED` 依赖，不自动扩大交付范围。

## 第三方原包映射

选择 `connections.feature_selections` 中的 `{key, mapping_path, integration_mode}`，映射旁置于 provider，原包不改写。原 `connections.native` 仍声明工具与根目录，实际 Skill 与 operation 列表由功能选择投影。原完整 catalog、映射摘要、交付 catalog、布局及实际工具分别保存。

采用功能映射的 connection key 重新计算本次 Skill 列表，不并入该连接旧的 `connections.skills`；其他连接及未采用映射的旧入口保持原选择。选中的 `BUILD_ONLY` Skill 仍可供搭建使用，但不因此交付给目标。

第三方真实未决请求还绑定原包描述、相关功能及其依赖的公开文件、Skill、工具文件和共享说明字节。相关来源变化后，旧决定不能被当作新来源已核对；原记录保留。未选功能专属文件变化、同字节目录迁移或改从 ZIP 读取，不使原决定失效；未声明真实未决条件时不另造请求。`check-selection` 也核对这些来源，即使本次只有资料、没有 native binding。没有来源绑定的历史记录不自动升级为已绑定决定：可信宿主核对原来源与原真实决定是否仍适用，按既有同范围补记方式关联新请求，不能伪造确认，也不把等义补记变成新的审批层。


原连接未采用功能映射时，行为保持原样。采用映射但只选资料时，不创建空原生调用绑定，交付仍标 `CATALOG_ONLY`、运行未验。ALL 存在未映射 Skill/operation 时列出缺口，不能把已映射子集冒充原包完整能力。

## 给目标交付什么

标准包用 `stack_handoff.py deliver --materials FILE --output NEW_PAYLOAD`；混用外接包用 `delivery.py prepare`（参数见 `--help`）。NEW_PAYLOAD 是宿主新准备目录，其内容拟置于目标的 `harness/capabilities/`。v2 生成 `delivery.json`、`capability-inventory.json`、`capability-inventory.md` 和 `decision-records.json`。外接包继续使用原布局交付器；标准包位于 name/version，混合交付时位于 builtin/name/version。

目标 AGENTS 或 Skill 引用所选 `target/INSTRUCTIONS.md` 及实际工具入口。说明片段可以列出全包功能，但以交付清单为本次选择；共享脚本中的未选子命令不是已授权能力。若需求要求该入口实际不可调用，应另以原包配置或明确桥接实现并检查，不能只靠清单隐藏。

`delivery_intents.py --payload NEW_PAYLOAD --output NEW_HOST_INTENTS --result reports/capability-apply.json` 生成初次普通文件创建意图和 Plan 片段。结果路径显式进入 required/allowed，payload 和意图留在目标写域外。`apply.py` 沿原 LOCAL 路由执行；重复读取结果不调用 apply。链接单列 `layout_steps`，不冒充 required 普通文件；由原 layout writer 在声明范围内写入、复核，不把链接展平成文件。该初次创建 helper 不用于猜测旧目标的升级/移除动作。

接收环境重新绑定本机工具，不复制 `.venv` 或开发机 profile：标准 v2 使用 `stack_handoff.py bind --delivery DIR --environment JSON --project-root DIR` 输出绑定，`call-delivered --binding JSON --tool ID -- ARGS` 产生 argv；外接仍用 `delivery.py bind/call`。这些调用准备入口不派发。宿主按既有权限执行并保存原报告。绑定与调用核对裁剪交付的真实文件、链接、权限和工具，不要求重新发现完整原安装。

## 独立检查和报告

`check_capability_delivery.py --target TARGET_CAPABILITIES --expected PROTECTED_SNAPSHOT --instructions TARGET_AGENTS --report NEW_REPORT` 核对四份清单、公开文件/布局、支持代码、目标引用及范围内多余文件。保护预期由可信宿主从已经审阅的最终交付/合并结果固定，不能从待验目标反向生成。受保护依赖需一同提供：本目录的 delivery/native/connections/environment/prepare/consume 等 helper，或固定通用包完整 helper 目录；不能回读生产者可写的检查依赖。输出兼容 STRUCTURED_V1，结构通过不代替实际功能检查。

`report_delivery.py --delivery .../delivery.json --evidence EVIDENCE --contexts CURRENT_CONTEXTS --read-build READ_BUILD_JSON --output NEW_REPORT_JSON` 只读归并。contexts 按 `能力@版本:功能` 给出当前 input_ref、expected_ref、checker_ref、environment_ref；evidence 是宿主按发生顺序归档的事实列表，另含 delivery_sha256、status、structure、behavior、command_ref、attempt_ref。report_ref 使用 `{path, sha256}` 指向实际报告，核对摘要、检查状态和命令。纯资料/配置需说明行为不适用及内容消费检查；宿主浏览器、检索等工作流不能借 Markdown 载体免验。

旧失败、ERROR、SKIP 和不匹配的历史证据均保留。缺当前 context 或报告、只有历史 PASS 时仍未验证。来源字段及“实际行为已核实”的含义由已有可信宿主和独立检查负责；该只读汇总不会自行授予接受、重新计数或证明收益。`--read-build` 显示原当前状态，与功能结果分列；完整宿主 JSON 不直接复制给生产者，公开交付说明只摘取适用事实及未验边界。

## 连续升级

沿 `upgrade.py` 的完整新选择准备新材料，新增 `feature_changes` 列明功能形态、usage、模式、依赖和标签变化。物理交付继续用原 G/C/N 与 merge/apply：G 是上次实际生成 N，C 是定制后的目标，N 是本次新生成；接受后的合并产物 A 不替换 N。保持旧输入和证据，冲突按既有决定处理。

明确保留但不再管理的文件列于 delivery.retained_unmanaged，包含 path、sha256、owner、decision_ref；其摘要按实际最终结果固定。保护检查不误拒这些文件，它们也不算新功能或新通过。共享文件仍被其他选中功能使用时保留实际所有者，不因一个功能移除就删除。

8 个新增版本为 qt-cmake@3、python-environment@2、data-summary@2、doc-export@2、host-review@2、local-dashboard@5、text-count@2、reference-notes@2。旧目录不变。doctor 只核对显式绑定路径和报告版本，不安装或执行 SDK；真实编译、导入、浏览器与服务仍分别验收。源码合入和预发布不代表用户实际部署已升级；未验范围见 [使用与验证边界](../../docs/CAPABILITY_ADAPTERS.md)。
