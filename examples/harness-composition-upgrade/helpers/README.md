# R3 普通文件辅助脚本

这些脚本只准备候选、应用明确的普通文件意图。它们不读写 Harness 控制库、接受事件或 lineage；`READY`、`APPLIED` 也不表示控制器或业务验收通过。

```sh
python -I -B /readonly/helpers/merge.py --inputs /readonly/inputs/inputs.json --output /candidate/merge-01
python -I -B /readonly/helpers/apply.py --manifest /readonly/inputs/apply.json --target /isolated/target --result outputs/apply-result.json
```

`file_states.py` 是两个入口实际加载的相邻依赖，运行时与入口一起放入声明的只读工具目录。`--target` 缺省为当前目录。这里的绝对路径都是示意，实际 argv、读写目录和 Python 绑定由执行请求填写。

## 文件状态及输入

状态为 `{"file":"relative-payload-path","executable":false}` 或 `{"missing":true}`。文件引用相对于清单，允许 `../` 引用其他已声明的固定输入目录；实际读取范围仍由现有运行授权决定。`executable` 表示目标执行位，载荷文件自身不必可执行。缺失与零字节文件不同。这里只处理字节、存在状态和执行位，不承诺复制扩展属性、ACL、链接或其他文件种类。

`inputs.json`：

```json
{
  "format_version": 1,
  "files": [
    {
      "path": "workflow.md",
      "C": {"file": "current/workflow.md", "executable": false},
      "G": {"file": "baseline/workflow.md", "executable": false},
      "N": {"file": "new/workflow.md", "executable": false},
      "owners": ["workflow-component"]
    }
  ]
}
```

`G:null` 表示没有可靠组件基线，输出 `PROJECT_INCREMENTAL_REQUIRED`，由 Codex 按项目增量核实；`G:{"missing":true}` 才表示基线明确不存在。已知基线按 `C=G → N`、`N=G → C`、`C=N → C` 处理，其余为 `CONFLICT`。一个文件可保留多个 owner，但只生成一个文件项。

`merge.py` 先读取全部输入，再向新建或空候选目录写 `candidate.json` 和 C/G/N 字节副本。每项保存 `inputs`、`source_refs`、`status`、`selected`、`resolved`；有冲突也保留三份内容。返回码为 0（全部 `READY`）、2（存在冲突或未知基线）、1（无效输入/准备失败）。准备失败可能留下部分候选输出，它不是已固定的完整候选，不能据此应用；更正后使用新的输出目录。不存在覆盖整个目标目录的操作。

## 明确应用与中断

`apply.json`：

```json
{
  "format_version": 1,
  "files": [
    {
      "path": "workflow.md",
      "action": "update",
      "expected": {"file": "current/workflow.md", "executable": false},
      "desired": {"file": "resolved/workflow.md", "executable": false}
    }
  ]
}
```

动作支持 `create`（旧缺失、新存在）、`update`（都存在）、`remove`（旧存在、新缺失）和 `leave-unmanaged`（不修改该路径；不以旧/新预期要求覆盖当前用户内容）。改名用明确的“创建目的路径，再删除原路径”两项表示；共享文件只更新一次。没有 G 的项目增量也可由 Codex 形成明确的 expected/desired 应用意图，不需要伪造 G。

应用清单及预期/候选载荷保留在目标写域外。检查实际祖先身份，不能用目标目录的大小写别名绕过这一已有要求。所有受影响文件先与 expected 或 desired 核对，任一不符则在修改前返回失败。合法继续时已达到 desired 的项标为 `ALREADY_DESIRED`，只处理剩余项；每项动手前再核对一次，发现新的用户修改就停止。目标文件路径必须相对且无穿越；重叠/重复文件路径、指向同一对象或重叠位置的路径别名、符号链接和非普通文件在这个示例 helper 范围内不接受，不改变其他工作流的资源规则。路径别名检查按目标文件系统识别管理项及诊断结果的位置，在任何目标写入之前完成；不把所有文件系统一律按大小写不敏感处理。别名冲突须先调整明确的应用意图，本次未增加大小写专用改名接口。

普通文件替换使用同目录唯一临时文件和 `os.replace`，异常时清理本次已创建的临时文件；不会回滚已应用的前项，也不承诺多文件事务或任意并发写入安全。完整/部分应用均须由真实目标检查和既有控制器观测核实。测试中的故障模拟只证明 helper 的文件恢复语义，不证明 Harness 的完整耐久恢复链路。

`--result` 是调用方明确声明的目标内诊断文件，可在合法重试时原子替换；不得与管理文件或其父子路径重叠，也不得覆盖输入载荷。原始 stdout 和控制器宿主观测仍由既有接收器保存。返回码为 0（文件意图全部处理）、1（失败）；结果的 `APPLIED` / `INCOMPLETE` 是自报诊断，不能据此接受产物、清除 `UNKNOWN` 或自动重放 command。输出文件及临时文件所在目录应在实际请求中声明，不能把逐文件意图描述为操作系统逐文件写权限。
