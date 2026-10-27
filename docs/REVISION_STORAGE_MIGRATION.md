# 控制库副本转换与恢复核对

这是开发维护工具，用于 `REVISION_V1` 与 `REVISION_BODIES_V1` 的隔离副本转换。逻辑协议仍为2.9。工具不迁移旧 authoring/hash 库，不切换活动控制库，不运行模型、业务或恢复命令，不产生新授权或扣减预算；不随通用运行ZIP交付。

先停止在待采用路径上的写入者并完成业务安全交回，再安排实际采用。本工具的 SQLite backup 可以在工程测试中的 WAL 写入期间取得一致快照，但这种能力不代表获得对任一活动业务库的操作授权。**本轮只验证隔离工程库，真实业务旧库未备份、迁移或缩减。**

## 准备独立候选

在源码根使用项目已绑定的 Python 3.11+ 解释器。`SOURCE_DB` 是明确选定的隔离库，`NEW_DIRECTORY` 必须不存在；旧库和旧转换输出都保留。

```sh
.venv/bin/python -B devtools/migrate_revision_store.py \
  --source /isolated/source/controller.sqlite3 \
  --output /isolated/new-conversion \
  --evidence /isolated/external-evidence.json
```

工具先检查可用空间，通过 SQLite backup 分页取得 `snapshot.sqlite3`（含已提交 WAL，不含未提交事务），再在独立事务中写 `candidate.sqlite3`。原事件ID、sequence、Program、revision、时间、正文、请求类型结构及有序返回均逐项比较，不用摘要或行数代替完整语义。摘要只用于固定副本身份和声明文件的版本核对。未知业务表不静默丢弃；遇到这种混合库需单独处理，不改变普通运行的规则。

`migration-report.json` 的 `DATABASE_CONVERSION_VERIFIED` 只证明库内转换比较通过，**不是采用批准或业务通过**。失败留下 `INCOMPLETE`，进程硬中断可能没有报告；两者都不能采用，重试另选新目录。不覆盖、删除或补写旧事件。磁盘预检仅确认快照的最低空间，转换膨胀、WAL及其他进程占用仍可能造成写入失败；事务失败保留原库和失败目录。

## 库外材料与路径

外部清单只列本次恢复实际需要的文件或有限目录。例如：

```json
[
  {"path":"/isolated/source/controller.commands/ATTEMPT-id/COMMAND-id","kind":"tree","role":"COMMAND_OBSERVATION_AND_REPORTS"},
  {"path":"/isolated/source/controller.verifiers/VERIFIER-id","kind":"tree","role":"PROTECTED_CHECKER"},
  {"path":"/isolated/product/output.json","kind":"file","role":"ACCEPTED_ARTIFACT",
   "expected":{"size":123,"sha256":"摘要来自原接受记录"}}
]
```

按原事件与捕获补齐 observation、原始输出、附件、resource-result/清理收据、受保护检查器及仍适用的已接受产物；`expected` 使用原记录绑定值，不由当前文件反向冒充旧期望。工具仅检查显式材料，不扫描整个项目猜测依赖。它另列事件中的 observation/runtime 根和未声明根，帮助核对清单遗漏；这仍不自动证明所有恢复依赖齐全。

检查保留原绝对路径、链接元数据及可读文件身份，并比较转换前后是否变化。目录内的目录链接只记录链接，不递归扫描链接目标，目标内容若属必要证据应另行明确列入。缺失、不可读、版本变化分别保留原声明和已知材料；`REVIEW_REQUIRED` 不能冒充完整证据。补回原字节后可重新调用 `evidence_inventory`核对；这是文件核对，不重跑业务或修改已审报告。正式收据另存，引用原冻结报告及候选身份。

目录扫描、条目元数据或文件读取失败时，在该项清单的 `errors` 中记录相对路径、操作、错误类型及系统错误号；该清单标为 `UNAVAILABLE`，整体库外核对保持 `REVIEW_REQUIRED`。即使前后两次出现相同缺口，也不能标为已完整核对。已发现的其他条目、可读文件及其他声明继续保留；合法空目录仍为 `AVAILABLE`。恢复读取条件后另存新的核对结果，不回改旧报告、重放业务或重新扣额。

本轮不实现路径重定位。转换后的旧事件仍指向原路径，新目录内的候选只作检查；不把临时转换目录当作已批准的新运行布局。需要搬迁观察目录、checker或产物时，另行安排位置映射及绑定验证，不能直接改事件字符串。本轮恢复测试使用可访问的原路径；完整捕获只取回、合法只复验仅消耗检查预算。

## 增量与回滚

报告记录快照revision及转换后源库revision。`source_advanced_since_snapshot=true` 表明旧源库继续前进，不能切换到落后的候选。即使为false，也只是本次观察，不证明写入者已经停止；工具始终标记未切换。实际采用时应核对最终静止版本、库外证据及读写域，保留原库与回滚材料。

若新格式副本后来已经追加事件，回滚准备必须从**包含这些增量的新库**重新取得一致快照，反向转换为独立内联库：

```sh
.venv/bin/python -B devtools/migrate_revision_store.py \
  --source /isolated/current-compact/controller.sqlite3 \
  --output /isolated/new-rollback-copy --to REVISION_V1 \
  --evidence /isolated/external-evidence.json
```

不能直接恢复旧快照而丢弃增量，也不双写两库或重新派发已执行命令。旧运行器不认识紧凑格式；本工具只提供反向转换候选，实际旧版本是否支持新增事件语义仍需另核对，不以物理格式兼容代替业务版本兼容。

## 验证与空间口径

`tests/test_revision_migration.py` 使用隔离工程数据覆盖WAL、一致快照、源追加、反向转换增量、事务/进程中断、空间不足、正文/结果异常、库外附件、原路径恢复、跨prepared、撤销及只复验。模拟磁盘不足与故障注入单列；真实 Python 子进程/SQLite工程检查不等同于真实模型、原生沙箱或业务部署验收。

数据库、WAL/SHM、原库归档、快照、候选、失败目录和最终包分别计量。新副本缩小不等于整机释放空间；没有删除旧库或活动采用行为。默认新库格式不变，选型、授权、预算和恢复门槛不增加。
