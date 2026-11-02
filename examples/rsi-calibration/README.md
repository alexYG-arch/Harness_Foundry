# 所选合同校准经验

这是一组可选 Wiki 候选材料，使用现有 RSI 查询和交付工具；不会自动加入所有 Harness，也不授权执行。条目仍为 `CANDIDATE`：工程样本验证不等于新任务采用或收益证明。

使用自己声明的 Python 解释器，在已有运行授权范围内准备所选支持：

```sh
/path/to/project/.venv/bin/python -B tools/prepare_rsi_delivery.py \
  --manifest examples/rsi-calibration/selection.json --output /new/selected-rsi
```

目标 Harness 可在需要时调用交付中的 `tools/rsi_wiki.py query`，从当前问题而非指定条目 ID 发起查询；例如“结构化结果的 null 与缺省字段如何校准”或“批处理原子失败如何核对实际文件”。条件声明如 `{"task_kind":"structured-result","contract":"explicit"}`，或 `{"task_kind":"file-batch","failure_policy":"atomic"}`。核对返回的条目、来源版本和适用限制，再用 `record` 保存采用或不采用理由。未命中、不适用和不采用均不阻止普通任务。

`methods.md` 是通用方法说明，不含正式保留输入、业务答案、模型授权或运行记录。需要的业务合同、工具、独立检查与预算仍由具体任务声明；响应字段的合法形态和批处理是否允许部分成功，不能由本集合替代合同决定。

新版本另存集合与条目，不覆盖旧查询和采用收据。目标部署是否已更新、真实新任务是否完成及效果是否改善分别验证；这份示例本身不证明这些结果。
