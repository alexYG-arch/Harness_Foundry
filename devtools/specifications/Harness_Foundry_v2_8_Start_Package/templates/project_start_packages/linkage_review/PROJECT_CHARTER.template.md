# Read-only Linkage Review Project Charter

## Identity

- `project_id`: `<LINKAGE-REVIEW-PROJECT-ID>`
- `project_role`: `READ_ONLY_LINKAGE_REVIEW`
- `program_id`: `<PROGRAM-ID>`

## Mission

构建只读 Linkage CLI，核验 Main Build、External Lab、Artifact、安装描述与运行证据之间的 ID、版本、Hash、来源和门禁关系。

## Authority and boundaries

- Linkage 只读取内容寻址证据并产生 PASS、FAIL 或结构化 Finding。
- Linkage 不修改 Main 源码、Lab、Artifact、认证环境或真实目标。
- Linkage PASS 不是 Conformance Certificate；证书判定仍由 External Lab 所有。
- 修复建议必须路由到证据 Owner，修复后按失效 DAG 回退，禁止就地改写历史 PASS。

## Exit evidence

CLI 自测、只读证明、跨工程版本矩阵、Finding/Repair Route 和 Linkage D 报告必须可复验。

## Stop rule

遇到写入请求、来源不明证据、Hash 漂移、错误 Owner 或未声明的版本组合时停止。
