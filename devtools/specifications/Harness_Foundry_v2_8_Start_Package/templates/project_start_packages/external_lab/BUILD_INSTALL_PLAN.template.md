# External Lab Build and Install Plan

## Ordered construction

1. 冻结 Shared Protocol 与 Pack schema。
2. 构建 Lab CLI 与可执行 validator；记录工具版本和 Hash。
3. 构建正向、负向和篡改 Fixture，证明错误输入不会假通过。
4. 在独立 Lab 环境运行自测，并发布接口描述供 Main Build 与 Linkage 登记。

## Candidate certification

1. 读取固定 Hash 的 Release Candidate Lock 与 Certification Install Receipt。
2. 验证安装来源、运行身份、Pack D、Linkage D 与 C4 证据。
3. 仅在全部门禁有效时签发 Certificate；否则生成结构化 Finding。

Lab 工具安装与 Harness 真实目标安装相互独立。Lab 没有真实目标安装权限，也不得代表用户产生该授权。
