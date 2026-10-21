# External Conformance Lab Project Charter

## Identity

- `project_id`: `<EXTERNAL-LAB-PROJECT-ID>`
- `project_role`: `EXTERNAL_CONFORMANCE_LAB`
- `program_id`: `<PROGRAM-ID>`

## Mission

构建独立的 Pack/Artifact/Runtime 校验 CLI、负向 Fixture 和证书签发面，验证 Main Harness 实际运行行为而非仅验证声明文件。

## Authority and boundaries

- Lab 拥有 Pack schema、校验器、负向 Fixture、Trusted Runner Attestation 校验和 Certificate 生成规则。
- Lab 不修改 Main Harness 源码，不以 Main 工程测试结果替代独立校验。
- 只有固定 Hash 的候选 Artifact、干净认证环境和完整 D/C4 证据才能进入证书判定。
- Lab 安装仅限独立 Lab 工具环境；不得安装真实业务目标。

## Exit evidence

Lab CLI 自测、正负 Fixture 结果、校验器版本/Hash、证书或结构化拒绝报告必须可复验。

## Stop rule

发现 validator 不可执行、负向 Fixture 假通过、运行身份不可证明、Artifact Hash 漂移或权限越界时立即停止。
