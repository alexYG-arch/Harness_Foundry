# R3 组装与保留定制的升级：S1–S3 源码接入

这里提供两个机制样例、三组业务验收材料、普通文件 helper 和 S3 入口/证据接入。详细操作见 [integration](integration/README.md) 和 [宿主协作工作流](integration/HOST_WORKFLOW.md)。它们用于准备与测试 R3 首片，不是已经由 Foundry 生成、接受或发布的目标 Harness。控制器、协议 2.9、G1/G2、授权和预算语义均未改变。

## 从哪里开始

- `mechanisms/doc/`：离线文档组件、用户章节/顺序及笔记、连续版本更新与无 G 的项目增量修改。
- `mechanisms/api/`：本机 HTTP 组件、旧响应合同、默认 timeout 10→15→30 与用户 20 的两次保留。
- `business/`：PRD＋设计、数据计算推理、市场调研的原始输入、独立预期、反例、版本化工作流样本和工具接入准备。
- `helpers/`：只处理显式列出的普通文件；比较 G/C/N、形成候选、按清单应用。没有整目录同步或控制器状态写入。
- `verifier/`：受保护机制/业务检查器，消费独立预期和实际宿主证据；语义、渲染、实际检索仍需独立执行与判断。
- `integration/`：生成 Generic 材料、固定宿主证据与接入步骤，不创建运行批准或第二控制库。

样本中的版本和 `expected` 是预先确定的测试材料；即使文件内容符合预期，也不是已接受项目 A。只有实际控制记录完成接受后，外层才保存 A/G 与接受身份的 lineage 引用。不得为示例补造 Program、attempt、Review 或批准。

## 文件 helper 的使用位置

`inputs.json`、`apply.json` 等是本目录的普通文件格式，不是新增 CLI/Plan/协议字段。状态 `{ "missing": true }` 表示文件不存在；`{ "file": "相对清单的有效载荷路径", "executable": false }` 指向实际字节及目标执行位。`G: null` 表示缺少可靠组件基线，与组件原来没有该文件不同。

合并只自动处理 `C=G` 取 N、`N=G` 保留 C、`C=N` 复用 C，其他情况保留三份输入并报告冲突；没有 G 时交给正常项目增量修改。组件和用户恰好修改不同 JSON 字段也不被简单字节比较冒充语义合并成功。样例中明确的语义整合结果可供源码测试使用，真实任务仍须核实差异并独立检查。

应用清单列出 `create`、`update`、`remove`、`leave-unmanaged`。改名表示先创建新路径、再移除旧路径；共享文件只整合为一条应用项，删除一个使用者不推导出删除共享依赖。应用前核对受影响文件，保留无关文件；已达到期望状态的项可在合法续行中复用。普通文件与协作单一写入者是这个 helper 的实现范围，不是对所有 Harness 的新增限制。

以下是后续 LOCAL 请求的 argv 形状；实际使用必须替换为已声明的绝对路径和现有 Python 工具绑定：

```text
python -I -B /readonly/helpers/merge.py --inputs /readonly/inputs/inputs.json --output /candidate/merge
python -I -B /readonly/helpers/apply.py --manifest /readonly/inputs/apply.json --target /target --result outputs/apply-result.json
```

候选、清单及其引用的实际输入位于应用目标外，并作为只读来源提供；相对 payload 引用必须保留原布局或连同清单一起重新绑定，不能只复制清单。helper 的目标目录、诊断结果和替换用临时路径都须落在已声明写域。执行位是目标状态的一部分；不存在与空文件严格区分。缺少输入或发现新用户修改时先整合该部分，不覆盖它。

逐文件临时文件加替换不提供多文件事务。helper 的重复运行测试只证明文件级继续处理，不证明原命令已经完成，也不授权重放命令。实际中断先读取已有宿主观测及控制记录，按现有恢复语义处理；`--result` 与 stdout 都只是诊断。完整命令的恢复、attempt 计数、跨 Program 交接和正式接受仍由现有 Harness 与外层承担。

## 独立检查与真实运行

S1/S2 测试在临时目录执行 helper，比较实际文件和独立预期，不从 helper 自报结果推导业务通过。DOC 的离线工具按固定独立预期核对正文引用和 Sources 对应来源。API 已在普通进程源码测试中核对实际回环 HTTP 的 health/items/unknown 状态、JSON 及服务关闭；这不等于原生资源权限或控制器验收。后续 Harness 本机 HTTP 检查仍须在单条检查命令内启动、请求并停止自己创建的服务，使用现有 `LOCAL_SERVICE` profile，保留既有 TCP/UDP 权限说明。

三组业务的产物必须由实际交付工作流运行得到。固定资料不证明实时检索，数据预期复算不证明模型解释合格，HTML 文件存在不证明渲染和交互合格。浏览器/搜索按已声明宿主流程接入时，分别记录宿主操作与机器接受；CODEX 子进程不会继承聊天工具。`ONE_ATTEMPT` 在完整尝试后交回，不是生成与检查之间的宿主评审暂停点。S3 选定 automatic → 独立宿主实际取证 → 后续 LOCAL reviewed；原 S4 的实际执行结果见下述 R3 进度。

真实候选/应用 Program 继续使用现有版本化搭建文档 Review 和完整范围批准；本目录及源码测试不提供替代入口。独立检查器须位于实施工作区外，读取受保护的预期和依赖；后续将 helper、材料和实际工具列入声明读取范围，不临时回读开发目录。

## 源码测试与验收范围

在 Foundry 源码根使用项目已有 `.venv`：

```sh
PYTHONPATH=src:tests .venv/bin/python -B -m unittest test_harness_composition_helpers test_harness_composition_mechanisms test_harness_business_fixtures test_harness_composition_upgrade test_harness_mechanism_integration test_harness_business_checks test_harness_business_integration test_harness_host_evidence -v
```

这些测试证明普通文件 helper、固定样例和独立预期的一致性。原选定 S4/S5 及后续真实材料复验已按 主源码工作区的 R3 进度记录（不在本包内） 完成，证据及适用边界以该记录为准，不由本地包检查推导。本目录仍未进入已发布 v0.5.0 ZIP，不更改既有 ZIP、版本或发布状态。主源码工作区新的能力接入计划 单列进度；WP01/02 只完成材料和环境准备代码，新目标、新输入、设备和看板验收仍待后续。
