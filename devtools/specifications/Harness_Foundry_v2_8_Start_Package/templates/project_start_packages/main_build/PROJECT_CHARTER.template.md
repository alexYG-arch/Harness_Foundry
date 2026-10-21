# Main Build Project Charter

## Identity

- `project_id`: `<MAIN-BUILD-PROJECT-ID>`
- `project_role`: `MAIN_BUILD_PROJECT`
- `program_id`: `<PROGRAM-ID>`
- `target_id`: `<HARNESS-ID>`

## Mission

按 G0、P1、P2、P3、P4 的门禁顺序实现 Main Harness，并产出可复现、可安装但尚未被认证的候选 Artifact。

## Authority and boundaries

- 本工程拥有 Harness 源码、单元/集成测试、构建输入与 Artifact 构建。
- 本工程不得自签 Conformance Certificate，不得把 Pack PASS 或 Linkage PASS 表述为认证通过。
- P3 必须执行，或由独立人工决定形成 `APPROVED_P3_NA_LOCK`；不得从 P2 直接跳到 P4。
- Certification Installer 是唯一能改变认证环境的角色。
- 真实目标安装必须等待独立的 `REAL_TARGET_INSTALL_AUTHORIZATION`，不得由构建完成或认证完成隐式触发。

## Entry and exit evidence

入口要求：Charter/Profile Lock 有效、Shared Protocol Lock 有效、External Lab 与 Linkage CLI 的兼容版本已登记。

出口证据：P4 Build Input Lock、可复现 Artifact、Pack B1、安装可用性证据、Release Candidate Lock。最终认证证书由 External Lab 产生。

## Stop rule

遇到未授权命令、失效前驱 Lock、重复失败、P3 缺失或真实安装请求时停止并生成结构化阻塞记录。
