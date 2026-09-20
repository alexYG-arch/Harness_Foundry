# Task CLI — 完整小型 PRD v0.1

状态：公开合成需求，不是运行授权。用途：验收 Foundry 从完整 PRD 搭建 Coding Harness，
再由 Codex 在该 Harness 下开发出可用程序。没有网络、账号或真实用户数据。

## 使用者与范围

单用户在本地终端维护任务。交付 Python 3.11+ 标准库程序 `tasks.py`、使用说明和测试；
不做 UI、服务端、同步、提醒、编辑标题或多进程并发写入。

## 接口和数据

调用：`python tasks.py --store FILE COMMAND`。FILE 的父目录已经存在。
标题去除首尾空白后必须非空，保留 Unicode 和内部空白。ID 为正整数，首次为 1，
新增递增；删除后不得重用。任务只有 `todo` 和 `done` 两个状态。

| 命令 | 正常 stdout JSON（对象字段顺序不限） | 行为 |
|---|---|---|
| `add TITLE` | `{"task":{"id":1,"title":"写报告","status":"todo"}}` | 添加并持久化 |
| `list` | `{"tasks":[任务对象...]}` | 按 ID 升序列出全部 |
| `list --status todo` 或 `done` | 同 list | 精确按状态筛选 |
| `complete ID` | `{"task":任务对象}` | 状态改为 done；重复完成保持 done |
| `delete ID` | `{"deleted_id":ID}` | 删除存在任务，不降低下一 ID |

存储文件为 UTF-8 JSON：`{"version":1,"next_id":正整数,"tasks":[任务对象...]}`。
task 对象精确包含 `id`、`title`、`status`。缺失文件在读取时视为空集合，不创建文件；
第一次 add 创建文件。已有文件须验证版本、字段类型、唯一正 ID、合法状态、非空标题及
next_id 大于全部现存 ID；不合法文件不可自动覆盖。每次成功修改先写同目录临时文件再替换，
避免把部分写入作为有效存储；不承诺系统断电或多进程并发事务。

正常退出 0，仅 stdout 输出上述一个 JSON。参数/数据错误退出 2，stdout 为空，stderr 为
`{"error":{"code":"错误码","message":"非空可读说明"}}`，不要求固定 message 文案：

- 空标题、非法 ID、非法状态或命令参数：`INVALID_INPUT`。
- complete/delete 找不到 ID：`NOT_FOUND`。
- 存储 JSON/结构不合法：`DATA_INVALID`，原字节必须保留。

不可预期的操作系统故障应明确失败，不改成业务成功；不将所有异常吞为上述业务错误。

## 验收（全 PRD 范围，不是 M1 切片）

A1：生成的 Coding Harness 包含本需求映射、开发/检查入口、停止与恢复说明；新 Codex
会话能够从工程内公开文件理解并使用它，不依赖 Foundry 作者聊天或私有路径。

A2：实际 CLI 完成 add 两项 → list → complete 一项 → 分别筛选 → delete → 再 add。
跨独立进程读取持久化结果，断言完整任务对象、状态、顺序及删除后 ID 不重用。

A3：空列表不创建存储；Unicode 标题往返；重复 complete 幂等。

A4：空标题、非法 ID/状态、未知 ID、损坏 JSON、错类型和重复 ID 的必要反例均符合
错误合同，原有效或损坏存储不被错误请求改写。检查元素内容而非只比数量。

A5：观察一次预定业务缺陷被独立检查拒绝、同范围内实际修复、复验和后继推进；另有
受支持的完整观测后中断恢复，不能重复已完成实施。测试故障安排公开，不藏产品需求。

A6：在同一份待验 Foundry 归档、隔离目录和实际 Codex 会话下完成搭建与开发使用；
本地单测/模板生成不能单独关闭 A1–A6。
