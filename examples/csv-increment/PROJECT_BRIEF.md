# CSV 质量工具增量 — 项目说明 v0.1

状态：公开合成项目，不是运行授权。使用此目录的 starter 作为既有代码，不修改原 starter。
Foundry 应先输出搭建文档，经人工 Review 后建立适配已有工程的 Coding Harness，
由 Codex 在该 Harness 下完成增量。Python 3.11+ 标准库，不联网、不安装依赖。

## 既有行为与保护

`python csv_tool.py summary INPUT` 返回 `{"columns":[表头...],"rows":数据行数}`，退出 0。
使用 UTF-8 CSV 和标准库 csv.DictReader，非空/不重复表头，保留列顺序和字段中的引号/逗号。
缺文件、坏编码或缺失/重复表头为退出 2，stderr JSON `{"error":"非空说明"}`。
保留既有命令、输出形状、公开函数及 starter 中的回归；不能删除旧测试来通过。

`USER_NOTES.md` 模拟用户未提交且与本需求无关的修改，其字节必须完整保留。
目标为独立复制目录，不覆盖输入 starter 或任何真实项目。可新增文件并修改 csv_tool.py，
不要求修改 Foundry 核心，不向核心硬编码本例名称。

## 新功能

`python csv_tool.py audit INPUT --required COLUMN [--required COLUMN ...] [--strict]`：

- 至少一个 required 列，参数列名必须非空且确实存在于 CSV 表头；重复参数按首次顺序去重。
- 值缺失、空字符串或全空白视为缺值；合法值原内容不改写。
- 数据行号从 1 开始，不计表头。输出精确为
  `{"rows":总数据行数,"invalid_rows":[{"row":行号,"missing_fields":[列名...]}]}`。
  invalid_rows 按行号升序，每行的 missing_fields 按去重后的 required 参数顺序。
- 无错误数据行或未使用 --strict 时退出 0；--strict 且发现缺值时退出 3，仍在 stdout
  输出上述完整报告。这不是检查器崩溃。输入/参数错误退出 2，stdout 为空，stderr
  为既有 error JSON；原 CSV 字节始终不变。audit 不写报告文件。

## 验收

B1：生成适配已有项目的 Coding Harness，并由新的 Codex 会话依据其规则实施增量。
B2：原 summary 的已知输入结果、函数 API 和原测试继续通过，USER_NOTES.md 字节不变。
B3：实际 audit 的正常、空数据集、缺值/空白、多列、重复 required、Unicode 和带引号 CSV
行为符合完整对象合同；不同进程、不同输入可复现，不能只对固定样例写死答案。
B4：--strict 的退出 3 与参数错误退出 2 有别；未知列/无 required/空列名/坏表头正确失败。
B5：同一个 Foundry 归档完成本例，不临场读取开发仓库或补写发行物；新源码没有业务特判。
验收代码与需求公开可读但不在目标实施写域。所有材料为合成数据，不使用私有 PRD。
