# 公开验收合同与检查器对齐（v0.1）

这是通用 Build 的输入/验证准备合同，不是新的授权层、领域 Schema 或万能判定器。
内部源码修复、定位和离线样例回归不新增人工门；外部合同实质变化仍回到既有搭建文档 Review。

## 责任与执行顺序

1. 宿主从已 Review 的搭建文档准备可观察的接口与验收依据。字段被精确比较时，公开其
   类型、元素格式、必需字段、身份/顺序/重复语义和必要非空示例；不要只给空数组。
2. 每个正/负 Case 在 Requirement IR 中声明 `acceptance_contract`，指向已声明 Source
   的实际行范围。它可以是搭建文档或明确的接口附件，不必再复制一份合同。
   由宿主根据已审文档填写，不要求用户手工写 JSON 或逐 Case 再批准。
3. 独立验证器的每个硬性断言应有上述公开依据。测试数据、私有实现、错误日志不能创造
   新的验收要求。算法、类名和内部存储结构仍由实施者决定。
4. 用公开正例与少量有意义反例检查本地工具和独立验证器。共享数据，不共享判定算法；
   至少一个非空正常例，覆盖当前发现的错误表示/错误身份。无需全量攻防矩阵。
5. 准备运行范围时，Foundry 解析各 Case 的合同定位，向 Readback 和实际任务上下文
   投影同一正文。缺失/越界/空白定位在运行批准、创建目标和模型派发前拒绝。
6. 运行失败先分流：明确实现不符合已公开要求才进入有限修复；合同未定义或互相矛盾
   应报告 `CONTRACT_GAP`，保留失败并暂停，不用更多实施尝试猜评分标准。

## Case 字段

```json
{
  "case_id": "REPORT-COUNT",
  "atom_ids": ["REQ-REPORT"],
  "description": "输出中准确报告无效行数。",
  "acceptance_contract": {"source_id": "PUBLIC-INTERFACE", "source_locator": "L10-L22"}
}
```

Source 仍走现有完整读取与绑定。静态编译/历史读取允许旧 Case 缺少此字段，但会校验
显式提供的引用；来源采集核对行定位；新范围准备必须覆盖全部 Case。已准备的历史范围
没有合同预检时不能再批准或派发，需要新提案/来源/范围及真实批准；历史事件不修改。
原本依赖已确认文档的 Review 规则不变。数字版本相同不能掩盖合同内容变化。

解析成功只证明“这个验收依据公开且可读”，不证明它足够精确、不证明每个断言都有依据，
更不证明全文需求覆盖。宿主语义审查与检查器行为测试仍须实际完成，禁止给定位 PASS
贴上“语义完整”标签。当前不会通过分析任意 Python 源码自动证明合同/检查器等价。

## 可复用的离线样例工具

`harness_foundry_factory.acceptance_contract.check_contract_examples(checker, examples)`
接收内存中的公开数据，checker 正常返回表示接受，抛出 `AssertionError` 表示拒绝。
其他异常原样抛出，避免将检查器崩溃计作正确拒绝。调用者负责 checker 的含义与副作用；
这个工具不是沙箱，不隐式派发模型或运行任何目标命令。

```python
examples = [
    {"name": "normal", "input": ["item-1"], "accepted": True},
    {"name": "wrong-element-type", "input": [{"id": "item-1"}], "accepted": False},
]
local = check_contract_examples(local_checker, examples)
independent = check_contract_examples(independent_checker, examples)
assert local["status"] == independent["status"] == "CONTRACT_EXAMPLES_MATCHED"
```

样例必须包含正常见证；验证器始终拒绝不算通过。结果保留逐样例差异且明确
`semantic_completeness_verified=false`、`target_accepted=false`。
工具不自动导入/运行用户代码，也不在范围准备时偷偷执行任意检查命令。具体工程须将
样例回归接入其检查器准备及 CI；原生权限/二级进程/零写验证继续按 Build CLI 执行。

## 失败路由

独立检查器退出 1，stdout 输出完整 JSON：

```json
{"status":"CHECKS_FAILED","failure_kind":"CONTRACT_GAP","reason":"公开接口未定义被精确比较的元素格式"}
```

原生 runner 和耐久观测恢复都将其归为 `ACCEPTANCE_CONTRACT_GAP`，禁止自动实现重试。
控制器保留 BLOCKED 尝试，推进返回 `HELD_ACCEPTANCE_CONTRACT`；Readback 的下一步是
`ALIGN_PUBLIC_CONTRACT_AND_VERIFIER`。已经发生的调用不退还预算、不改写原失败记录。
正常 ASSERTION 仍走有界实现修复；崩溃/缺依赖仍是基础设施问题；未知副作用仍须核对。
该分类依赖实际检查器/宿主识别缺口，不宣称自动理解所有语义矛盾。

合同修订必须同时处理公开说明、样例、实施输入、相应验证器及回归，不单独放宽检查。
新源文件/检查器绑定必须进入后续新范围；禁止直接修改已绑定旧文件以复活旧批准。
没有新增 Hash、逐步人工批准、独立数据库或“自评已完成”的验收权威。
