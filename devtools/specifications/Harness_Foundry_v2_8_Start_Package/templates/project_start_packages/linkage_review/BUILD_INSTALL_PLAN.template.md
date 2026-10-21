# Linkage Review Build and Install Plan

## Ordered construction

1. 冻结 Shared Protocol 和跨工程 ID/Hash schema。
2. 在独立工具环境构建 Linkage CLI。
3. 运行只读负向测试，证明候选目录、Lab 和安装环境不会被修改。
4. 发布接口描述并运行 Main/Lab 注册前的版本兼容预检。

## Review execution

Linkage D 只读取 Release Candidate、Certification Install Receipt、Installed Target Descriptor 和运行证据。失败时生成 Finding、Owner Route 与受影响 Lock 列表；修复动作由对应工程执行，Linkage 仅复验。

本工程没有 Harness 安装、证书签发或真实目标安装权限。任何此类命令都必须拒绝。
