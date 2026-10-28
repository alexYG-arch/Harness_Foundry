# DOC 结构化材料导出

本包复用 R3 DOC v3 的导出形式，接受项目声明的 JSON 规则、结构化笔记和来源，实际生成 Markdown。包不读取搭建聊天或 Foundry 私有运行目录；交付后的新任务仍使用相同入口，只替换本次输入及新输出位置。它不负责把任意 WCT 原文自动提取为笔记，也不声称 PDF、视觉排版或语义完整性已验收。

项目维护 `config.json`：`title`、有序 `sections`（每项 `id`、`title`）、可选布尔 `include_source_titles` 和 `show_priority`。`notes.json` 是笔记数组，每项含 `section`、`text`、`source`，启用优先级显示时还含 `priority`。`sources.json` 是来源数组，每项含唯一 `id`、`title`、`locator`。笔记必须指向已声明的章节和来源；重复章节或来源编号、未知引用及缺字段应报错，不静默丢弃事实。重复笔记保留，是否多余由项目独立预期判定。来源列表只导出本次实际引用的来源。

先按已选包版本与本机环境调用现有 `consume.py` 核对，使用其返回的实际 Python 和工具入口：

```
<python> -I -B <delivered>/export_doc.py --config <project-config.json> --notes <new-notes.json> --sources <new-sources.json> --output <new-output.md>
```

输入与包文件只读，输出必须是新文件，既有文件不会被覆盖。标题、章节顺序和显示选项属于项目定制，不因包升级重置。旧产物、旧输入和证据继续保留；后续升级仍用现有版本选择、G/C/N、合法接续及报告恢复流程，本包不新增预算或恢复控制器。

独立检查使用 `check_doc.py --tool <delivered>/export_doc.py --config ... --notes ... --sources ... --expected <private-expected.md>`。项目在搭建前独立写出本次**完整** Markdown 预期及原材料到笔记的核对规则；不能把本次生产输出复制为预期。`check_doc.py` 与预期均列入独立检查依赖，由现有流程准备并保护。设置 `FOUNDRY_VERIFIER_ROOT` 时检查器和预期必须来自该受保护副本。私有预期不放入生产者包、项目实施输入或导出命令。

检查器只执行一次实际 CLI，在本次 `FOUNDRY_SCRATCH_DIR` 子目录生成文件，对完整非空行序列进行比较，仅忽略空白行；额外事实、重复正文、错误引用、主标题和首章之间的额外内容均会失败。报告记录实际命令（绑定 Python 以 `-I -B -c` 运行受保护的 `runpy` 包装器，再执行交付 CLI）、输入/工具/预期/结果摘要、返回码和实际导出正文，沿 `FOUNDRY_REPORT_DIR/summary.json` 的 `STRUCTURED_V1` 归档，随后清理自己的临时导出；成功清理后仍可从归档报告读取正文，恢复应取回原报告，不重放本次导出。独立使用可传 `--report <new-report.json>`；报告也不会覆盖，已有报告时在执行前退出。资源模式必须使用声明的 scratch，独立调用未声明时可使用系统临时目录。`--timeout` 是这一次导出子进程的超时，默认 30 秒，不创建额外尝试额度。

明确产品输入路径或结构错误、CLI 错误导出归为 `ASSERTION`；受保护预期不可读、ENOSPC、scratch、进程启动或超时故障归为 `ERROR`。CLI 的一般非零退出仍按产品失败处理；没有识别到产品路径的 OS 故障不会自动要求修改业务内容。

工程测试只证明包入口与独立检查可用。真实 V4 仍需交付件在新会话处理未参与搭建的授权 WCT 材料，独立验证原文提取、内容、引用和格式；工程夹具和旧 R3 报告不能代替该验收。
