# DATA 精确汇总能力 v1

本包提供可独立运行的 CSV 汇总工具和独立预期比较器。Foundry 只负责选取和交接这些文件；交付的目标 Harness 使用同一 CLI 处理新输入，不依赖 Foundry 的 Python 模块。业务口径由项目给出，本包不内置 AICut、付费状态、修订去重或项目答案。

```sh
/项目/.venv/bin/python -I -B /能力包/summarize_csv.py \
  --input /项目/新输入.csv --config /项目/汇总配置.json --output /项目/results/新结果.json
```

输入为 UTF-8 CSV（允许 BOM）；表头必须唯一，每条记录与表头等宽。数字为有限十进制字符串，可用指数表示，不猜逗号小数、货币符号或单位。使用有理数精确求和和相除，最终才舍入，不经过二进制浮点数。CLI 只写显式的新结果文件，不覆盖已有结果、不回写能力目录，不启动服务、不安装依赖、不联网。输出目录由项目准备；失败保留原输入和已有结果。

## 项目配置

配置中以下字段均为显式选择；下例只说明结构，不是业务推荐或独立预期：

```json
{
  "schema_version": "1.0",
  "group_by": ["region"],
  "filters": [{"column": "stage", "equals": "included"}],
  "rows": {"key": ["item_id"], "duplicates": "error", "missing": "error"},
  "metrics": [
    {"id": "amount", "op": "sum", "column": "amount", "unit": "yuan", "scale": 2, "rounding": "HALF_EVEN",
     "unit_column": "amount_unit", "unit_factors": {"yuan": "1", "fen": "0.01"}},
    {"id": "items", "op": "count", "unit": "items", "scale": 0, "rounding": "DOWN"},
    {"id": "per_item", "op": "ratio", "numerator": "amount", "denominator": "items",
     "zero_denominator": "error", "unit": "yuan/item", "scale": 2, "rounding": "HALF_UP"}
  ]
}
```

- `group_by: []` 表示全表汇总；分组顺序为最终保留记录首次出现顺序。没有记录时，无分组输出一组零总数；有分组输出空组列表。
- `filters: []` 表示不筛选；非空只支持多个列的字符串相等比较，按 AND 组合。需要更复杂业务筛选时，由项目显式准备输入并保留来源，不添加隐式规则。
- `rows.key` 为项目去重键。`duplicates` 必须明确为 `error`、`keep_first`、`keep_last` 或 `all`；首条/末条指输入记录顺序，不推断版本或日期。空 key 只配 `all`。键在整个筛选后的表中生效，不自动加上分组字段。
- 固定处理顺序是筛选、检查所需字段的空值、解析数值与单位、处理重复键、分组汇总。被筛除记录不参与后续数据校验；所有保留候选（包括重复记录）必须数值合法。`missing` 仅对消费字段的空字符串选择 `error` 或 `skip`；非法数字、未知单位、缺列和错列数仍报输入错误，不当作空值跳过。空白字符串不自行清洗。
- `sum` 汇总指定列；`count` 计保留记录数；`ratio` 仅引用同组的 sum/count 指标，分母由项目明确指定，不自行选取“总数”。零分母明确选 `error` 或 `null`，后者输出空 value/exact。比率和计数的单位名称由项目给出，不自动作维度推断。
- 只有 sum 可选 `unit_column` 和 `unit_factors`，须同时给出。换算系数是严格大于零的十进制字符串；只接受列明单位。未给出时输入已是项目声明单位。不要混入价格、汇率或随记录变化的业务换算。
- 每项都声明 `scale`（非负整数）、`rounding`（`HALF_UP`、`HALF_EVEN`、`DOWN`，DOWN 为向零截断）和 `unit`。负数允许；不输出负零。未知配置项拒绝，避免拼错参数后静默改变口径。方法只有以上三种，不是计算表达式 DSL。

结果绑定原始 CSV 和配置字节的 SHA-256；这只是输入身份，不证明业务正确。输出保留每条纳入记录的序号、分组、键、各基础指标的精确贡献，以及每条排除记录的原因。`record` 是去掉表头后的逻辑记录号，不是物理行号。组结果同时给出显示字符串与约分后的 `exact.numerator` / `exact.denominator`，可据原输入复算；精确结果与逐行明细都属于验收内容。

## 独立预期与保护副本

项目根据自己的合同另写完整 `expected.json`，或由与生产算法独立的项目计算方法生成。它包括结果的 `schema_version`、`summary`、`groups`、`rows`、`excluded` 五个字段，**不含**输入/配置哈希；检查器会从本次传入文件独立计算哈希。禁止从本次产品结果直接复制 expected 当作正确性证明。包内不携带业务答案，预期不能放到 producer 的 sources、runtime_files 或 shared 清单。

```sh
/项目/.venv/bin/python -I -B /受保护副本/capabilities/data-summary/check_summary.py \
  --input /项目/新输入.csv --config /项目/汇总配置.json \
  --actual /项目/results/新结果.json --expected /受保护副本/expectations/data-new.json \
  --report /独立结果目录/summary.json
```

`check_summary.py` 不导入生产脚本、不重新运行计算命令。它比较完整独立预期和输入绑定，包括额外字段、错误分母、丢行、重复行、精度和舍入变化；能否发现业务错误取决于项目预期的独立性与覆盖。错误的项目预期不会被本包自动纠正。

包清单只将检查器列为 `verification_files`。宿主还须将项目 expected 映射进 `verification_root` 并纳入现有 `checker_files`，检查命令用 `verifier://capabilities/data-summary/check_summary.py` 和对应 expected 路径。存在 `FOUNDRY_VERIFIER_ROOT` 时，CLI 要求自身与 expected 实际来自该受保护目录；省略 `--report` 时写入 `FOUNDRY_REPORT_DIR/summary.json`。报告沿用 `STRUCTURED_V1` 的 case/command 绑定和 `data-summary` check。实际结果不符归 ASSERTION；独立预期/检查输入不可读等环境问题归 ERROR。独立运行允许显式 report 路径，此时 standalone 报告不能直接充当宿主接受。

项目继续使用现有 Plan、资源声明、检查、接受、预算和恢复入口。交付时复制/保留声明的包、解释器调用入口和项目配置，沿选定版本的 `tool_bindings` 调用；实际消费前核对 `check_selection`，包改变后重新准备材料，不复用旧接受。本包不引入调度器、自动重试、缓存接受或新的通用限制。临时目录工程测试不等于真实数据业务、新设备或目标 Harness 新任务验收。
