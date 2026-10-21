# API 本机服务机制

合成需求：交付服务、客户端和配置，`/health` 返回 `status:ok`；`/items` 返回原样的两条合成 items；未知路径404。v2新增 health `api_version:2`；v3变为3并增加 `item_count:2`，已有响应合同继续成立。客户端必须实际使用配置 timeout，不能只保留一个未读取的字段。

| 阶段 | G 默认值 | C 用户值 | N 默认值 | 语义参考候选 |
|---|---:|---:|---:|---|
| [第一轮 inputs](scenarios/upgrade-1/inputs.json) | 10 | 20 | 15 | [after-v2](expected/after-v2/config.json)：20 |
| [第二轮 inputs](scenarios/upgrade-2/inputs.json) | 15 | 20 | 30 | [after-v3](expected/after-v3/config.json)：20 |

`versions/` 保存实际代码和配置；`expected/` 只是 NOT_RUN 参考候选，不是已接受 A。config 两次均冲突；服务代码可确定性升级；客户端及合成数据保留。第二次真实升级必须读取实际 G/A/C，不从本表推定旧运行成功。

工具准备：服务和客户端只用 Python 标准库，绑定现有 `.venv/bin/python` 及所需只读依赖。`verifier/check_mechanisms.py --kind api --target <实际目标> --expected <受保护 api-v2或v3.json>` 的默认模式只在进程内检查业务合同及客户端真实传入的 timeout，不建立监听，不等于 HTTP 已验收。

S4 实际 HTTP 检查使用同一检查器加 `--live-api`。单条检查命令创建自己持有的 `127.0.0.1:0` 服务，读取分配端口，由独立检查器直接请求 health/items/unknown，核对真实 HTTP 状态分别为 200/200/404 及对应 JSON，同时保留产品客户端调用和配置 timeout 检查；finally 关闭 listener 并等待自己线程退出；不探测或借用已有服务。客户端禁用继承代理。本次修复已用项目 .venv 在普通进程中运行 v2/v3 及故意返回错误状态/响应的反例，核对成功与失败后的服务关闭。它不证明原生沙箱网络权限、资源报告或控制器恢复已验收。

请求/范围接入准备（不是已批准请求）：

1. 沿既有版本化搭建文档 Review、来源采集、prepare 完整 Readback、批准及 advance。候选/应用使用独立控制库，真实 ID、绝对目录、预算由实际准备绑定，不抄造 fixture 记录。
2. 声明 Python/executables、源文件、独立检查器及 expectation，控制库在工作区外，检查器依赖实际读取受保护副本。产品源码只读检查时不产生产品缓存，`-B` 避免 pycache。
3. HTTP 分支的 verification 配置既有资源 `network:{"mode":"LOCAL_SERVICE","tcp":"LOOPBACK"}` 并引用该 profile；报告需按当前资源合同接入宿主采集，示例检查器 stdout 只作诊断，不能直接自报控制器接受。具体 request/scope 和 STRUCTURED_V1 报告适配已在 S3 落成，见 [接入入口](../../integration/README.md)。
4. 当前原生 LOOPBACK 能力实际含回环 TCP、UDP 全部端口，另有端口53例外；不宣称只准本 HTTP 实例/端口或 TCP-only。服务自身只绑定127.0.0.1，不以此夸大沙箱隔离。
5. 恢复沿既有耐久观测/资源回收；完整 capture 不重放服务命令；未知效果按原语义处理。实际中断、采集恢复、沙箱权限、超时撤销后的清理仍属 S4 未验收范围，不由离线 handler 测试代替。

本例不需要云端账号、SQLite或公网服务；这些不是业务验收的通用禁令。

S3 的交付流程：先用 [材料生成器](../../integration/README.md) 准备 candidate（v1 直接新交付）或后续 apply；核对真实源、工具和范围后沿 Generic 入口运行。保护检查命令为 `python -I -B verifier://check_mechanism_resource.py --kind api --stage <实际版本> --target <实际目标>`，不只依赖 stdout。使用说明随本示例交付，实际目标的运行与来源/接受交接另在 S4 留证；不把参考候选复制当成模型组装。
