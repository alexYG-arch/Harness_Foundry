# DOC 离线文档机制

合成需求：读取 `data/notes.json`、`data/sources.json`，生成 Markdown 周报，事实、引用和来源应完整。用户把标题改为“我的周报”，把“先做什么”放在“本周要点”前，保留 `USER_NOTES.md` 的完整字节。不能用重新生成默认报告覆盖这些定制。

| 阶段 | 实际输入 | 参考候选 | 独立预期 |
|---|---|---|---|
| 第一轮 | [inputs](scenarios/upgrade-1/inputs.json)：v1 G、用户 C、v2 N | [after-v2](expected/after-v2/config.json)：保留用户标题/顺序，新增来源标题显示 | [doc-v2](../../verifier/expectations/doc-v2.json) |
| 第二轮 | [inputs](scenarios/upgrade-2/inputs.json)：v2 G、上轮参考 C、v3 N | [after-v3](expected/after-v3/config.json)：再次保留定制，新增优先级 | [doc-v3](../../verifier/expectations/doc-v3.json) |
| 项目增量 | [inputs](scenarios/incremental/inputs.json)：G 为 null | [after-incremental](expected/after-incremental/config.json)：只加标题“（补充版）” | [doc-incremental](../../verifier/expectations/doc-incremental.json) |

上述输入与候选都只是固定样例。真实第二轮的 C/A/G 应来自实际接受后的读取与用户当前内容，不从参考候选推定上一轮已通过。两轮 config 均有真实语义冲突，须正常 Codex 整合；`tools/render.py` 可确定性升级。无 G 增量不是模板更新，不伪造 G。

工具准备：Python 标准库，使用已有项目 `.venv/bin/python` 的实际绝对路径。独立临时目标复制 `custom/current/` 后，可运行 `python -I -B tools/render.py --root . --output outputs/report.md`。独立检查器使用 `--kind doc --target <实际目标> --expected <受保护 expectation>`，以自身绑定的 Python 实际执行该 CLI，将导出文件写到本次专属临时目录，再检查真正导出的内容和产品备注。实际 CLI 的产品路径或文件布局错误，仅在错误码为 ENOENT、ENOTDIR 或 EISDIR，且捕获路径明确在实际产品根内时归为 ASSERTION；ENOSPC、权限、scratch、无路径及进程故障仍为 ERROR，不要求产品自动返工。诊断保留异常类别和绝对路径；这是局部错误分类，不跟踪识别具体读取操作，也不增加通用权限规则。资源入口使用已声明 scratch；独立无资源调用自行创建临时目录，两者完成后只清理自己的临时输出，产品文件保持只读。CLI 非零退出、漏写文件或错误导出内容均不能由正确的 `render()` 函数掩盖；错误归属按上述产品与设施范围区分。正文事实/引用及 Sources 中完整编号—来源对应均与受保护的独立预期比较，不因标题和 locator 出现在全文就接受，也不看 apply 自报结果。源码测试已覆盖固定参考候选和故意破坏；本轮路径错误分类补修的复验结果另见 R3 实施准备第 8.1 节。S3 已补实际材料入口与资源报告适配；模型选组件、真实工作流加载、原生沙箱/控制器接受仍待 S4。

请求准备沿现有 Generic Build：版本化搭建文档包含上述事实、两次升级和增量合同；来源采集包含实际需求正文；`source_read_roots` 明确包含固定 C/G/N、helper、Python依赖；独立检查器放工作区外。候选及应用使用不同控制库，应用声明实际目标目录、逐文件 effects、产物和检查器命令；正式 ID、路径、预算与完整 Readback 使用实际准备返回。这里没有已批准 request 或新增 CLI 字段。

本机制离线；不宣称 PDF、视觉排版、原生设计对象或搜索验收。

S3 的交付流程：先用 [材料生成器](../../integration/README.md) 准备 candidate（v1 直接新交付）或后续 apply；核对真实源、工具和范围后沿 Generic 入口运行。保护检查命令为 `python -I -B verifier://check_mechanism_resource.py --kind doc --stage <实际版本> --target <实际目标>`，不只依赖 stdout。使用说明随本示例交付，实际目标的运行与来源/接受交接另在 S4 留证；不把参考候选复制当成模型组装。
