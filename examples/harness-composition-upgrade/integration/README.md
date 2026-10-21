# S3 材料生成与接入

这些 stdlib 工具生成可审阅的普通 JSON 材料，不创建目标、控制库、批准或接受记录。实际工具协作与证据取回见 [HOST_WORKFLOW](HOST_WORKFLOW.md)，业务文件合同见 [OUTPUT_CONTRACTS](../business/OUTPUT_CONTRACTS.md)。

使用项目 `.venv/bin/python -I -B` 调用：

```text
mechanism_requests.py --kind doc --stage v2 --phase candidate --bindings /实际/bindings.json --output /新/materials.json
mechanism_requests.py --kind api --stage v3 --phase apply --bindings /实际/bindings.json --output /新/materials.json
business_requests.py --group prd-design --version v1 --phase automatic --bindings /实际/bindings.json --output /新/materials.json
business_requests.py --group data-reasoning --version v2 --phase reviewed --bindings /实际/bindings.json --output /新/materials.json
```

bindings 中的路径都用真实绝对路径。通用字段为 `program_id`、`requirement_path`（本次所选阶段的完整版本化搭建文档）、`workspace_root`、`verification_root`、`resource_root`、`python_executable`、`python_read_roots`、`codex_executable`、`model`、`max_attempts`、`max_task_attempts`、`command_timeout_seconds`、`expires_at`。数值和模型按实际准备决定，示例不提供通用默认限次或虚构授权。输入/检查器/资源根与目标写域分开；Python 读取根只包含实际必要依赖，不把整个仓库作为默认根暴露独立答案。

| 入口 | 额外绑定与可用路径 |
|---|---|
| mechanism candidate | `current_root` 是明确的当前输入；v1/v2/v3 提供 `component_new_root`，v2/v3 另提供真实 `component_old_root`。v1 无历史 G/A；incremental 只适用于 DOC 且不提供虚构旧 G。实际文件清单见生成器 `PRODUCT_FILES` |
| mechanism apply | v2/v3/DOC incremental 提供 `candidate_root`、`apply_manifest`、`helpers_root`，并保留冻结的 `current_root`；实际 target workspace 由宿主按原流程准备。manifest 的 expected/desired 指向冻结当前输入/候选字节，使用原 helper 的逐文件继续语义。v1 候选目录本身就是新交付，不走 apply |
| business automatic | `group_root` 指向三个固定业务组之一；V2 另提供 `prior_outputs_root`，逐文件读取真实 V1 的 outputs 以保留业务决策；V1 不伪造前序 A。可选 `handoff_path` 提供普通只读历史事实；不会将其中旧 ID 写入当前控制字段 |
| business reviewed | 提供 `prior_outputs_root`（本次已审成果）、`host_evidence_root`、`helpers_root`、`apply_manifest`（待保存位置）。`market-live` 只接受 reviewed，group_root 指向 market-research，成果只用 live_outputs |

返回值含 `request`（requirement_ir/Plan 1.2）、`scope`、`source_manifest`、`preparation`。`preparation` 的 `MATERIALS_ONLY_NOT_APPROVED` 明确尚未取得批准；不把样例 program_id 或空 accepted_A 视为运行事实。来源读取定位涵盖完整搭建文档，因此正文须与本次阶段及 Case 范围一致；S4 总安排用于准备各阶段，不把其中其他组或后续阶段的全部义务当作单次 automatic 已完成。返回材料不包含 `document_review`、`expected_revision`、`idempotency_key` 或事件 ID，这些必须沿[既有 Generic CLI](../../../docs/GENERIC_BUILD_CLI.md)用真实确认和命令返回值补齐。

## 准备受保护依赖

机制 `verification_root` 保存 `check_mechanism_resource.py`、`check_mechanisms.py` 及所选 `expectations/<kind>-<stage>.json`。wrapper 自动作为 verifier:// 入口快照，其余判定依赖由 checker_files 明确列入。DOC network NONE；API 使用现有 LOCAL_SERVICE、tcp LOOPBACK，保留现有实际回环 TCP/UDP 权限说明；报告分别含内容/API 及服务清理检查。

业务 `verification_root` 保存 `check_business.py`。按 `preparation.verifier_inputs` 的逐项 `source → verification_root/path` 固定所选 fixture 和已审 host evidence；它们不进入生成者读取域。reviewed 另把 `preparation.apply_manifest` 原样保存到 `preparation.apply_manifest_path`，相对 payload 布局不能改变。仅保存材料不创建目标或推进任务。

准备 host evidence 时，helper 输入审阅材料的 `evidence_refs` 相对 `--evidence-root`（例如 `screenshot.png`）；helper 输出到 `host-evidence/evidence/` 并将最终引用改为 `evidence/screenshot.png`。输入与输出的完整小例见 [宿主工作流第 4 节](HOST_WORKFLOW.md#4-固定真实证据再独立检查)，不要把最终引用原样当作原始工具记录根下的文件名。

Generic prepare 会建立真正受保护副本。argv 的 `verifier://...` 必须指向普通文件：本示例用 `manifest.json`、`review.json` 文件锚点，检查器从它们的受保护父目录读取声明依赖。检查器必须使用实际注入的 case/command/report/verifier 环境，不回退开发目录。

独立检查写 `summary.json`/STRUCTURED_V1，由既有采集、归档、清理和恢复消费。automatic 只检查声明的自动准备合同；reviewed 读取真实独立证据并比较所审字节。旧报告不通过重放命令补造；新任务的正常复制/检查消耗只归新任务，旧消耗和未知影响不被清零。

reviewed 材料额外提供 `preparation.advance_request`，内容仅为 `{"advance_mode":"ONE_ATTEMPT"}`；补入实际 reviewed Program/prepared/revision 后使用既有 `advance-build`，每次交回先读报告。固定 LOCAL 复制器不能修复业务失败：真实 FAIL 保持 ASSERTION，由外层通过普通 handoff 将证据交回原 CODEX 的现有返修入口或原宿主修复流程，不将外来 attempt ID 放进 `basis_attempt_ids`，不连续重派同一复制器。ERROR 处理证据或设施，不改产品；真实修复后固定新证据并准备新 reviewed 任务，保留旧证据和消耗。具体返修条件及原完成分支沿 [Generic CLI](../../../docs/GENERIC_BUILD_CLI.md#已接受产物的额外缺陷返修)，此模板不授予权限、不新增门禁。

## 源码验证和待验收

`tests/test_harness_mechanism_integration.py`、`test_harness_business_checks.py`、`test_harness_business_integration.py`、`test_harness_host_evidence.py` 覆盖计划/完整 scope、受保护依赖、实际普通进程 HTTP、报告分类、声明成果复制与文件级续行。测试以合成产物和合成 host review 检验接入合同，不是实际模型或业务判断。原选定 S4/S5 已按 主源码工作区的 R3 进度记录（不在本包内） 完成；这些源码测试本身不等同于真实业务证据。本目录不在既有已发布 v0.5.0 ZIP 内。主源码工作区新增 WP01/02 准备入口（`examples/capability-adapters/`，尚未列入当前分发清单） 保留这些固定样例语义；新任务、能力升级及设备验收仍按新计划另行完成。
