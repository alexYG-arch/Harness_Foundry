# Main Build and Install Plan

## Ordered build

1. 验证 Shared Protocol、External Lab 和 Linkage 接口版本。
2. 按 `G0 -> P1 -> P2 -> P3 -> P4` 执行；P3 仅可由证据化的人工 N/A Lock 替代。
3. 冻结 P4 Build Input Lock，运行 Pack A、B0、C 后构建 Artifact。
4. 对已构建 Artifact 运行 Pack B1 与隔离 Installability；不得从源码目录回退加载。
5. 形成 Release Candidate Lock，将 Artifact 交给 Certification Installer。

## Certification boundary

Certification Installer 在单一新建认证环境中安装固定 Hash 的 Artifact；External Lab 运行 D/C4 并签发或拒绝 Certificate。Main Build 不创建证书。

## Real target install

真实目标安装不是本计划的自动后继步骤。仅当 Certified Release Lock 有效且收到单独、未过期、目标绑定的 `REAL_TARGET_INSTALL_AUTHORIZATION` 后，Installer 才能生成真实安装命令与回执。任何缺失授权的请求必须停止。
