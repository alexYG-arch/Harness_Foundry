# v2.6 → v2.7 迁移映射

## 迁移目标

v2.7 不覆盖 v2.6 原文。它把 v2.6 的大体积协议重组为可按需加载的作者指导包，并修复会诱导模型假通过、跳阶段或运行错误入口的约束缺口。

## 核心映射

| v2.6 主题 | v2.7 模块 | v2.7 调整 |
|---|---|---|
| 方法定位、Authority、Profile | `docs/00`、`docs/01` | 明确本包只是作者指导，不是目标执行包 |
| Charter、Phase Design、G0-P4 | `docs/03`、`docs/04` | “推荐顺序”升级为带前驱 Hash 的状态机 |
| Workpack、Capsule、Execution Mode | `docs/05` | Authoring、Registration、Execution 机械隔离 |
| Runtime Ownership、Stage Receipt | `docs/06` | 自报 receipt 升级为可信 Runner/Lab attestation |
| Detail Fidelity、Intent Atom、R/F | `docs/07` | Intent Atom 接入外部 Conformance Interface |
| Conformance Interface、Pack、Lab | `docs/08` | Main、Lab、Linkage 三工程和 Pack 数据边界明确 |
| Package、Install、Release Lock | `docs/09` | B0/B1、Candidate Lock/Certified Lock、三环境拆分 |
| Linkage、Repair Workpack | `docs/10` | 单一 owner、下游自动失效、重建/重装/再认证 |
| Positive/Negative Acceptance | `docs/11` | 增加同形伪造、重放、篡改、跳阶段、源码回退负例 |

## 已修正的 v2.6 冲突

### Pack Binding 循环

v2.6 曾在 Artifact 构建前要求完整 Pack Binding，同时又要求 Pack 绑定 Artifact Hash。v2.7 拆为：

```text
B0_NORMATIVE_BINDING
→ PACKAGE_BUILD
→ B1_RELEASE_ARTIFACT_BINDING
```

### Release Lock 循环

v2.6 同时出现“P4 Gate 生成 Release Lock”和“Release Lock 必须绑定 Certificate”。v2.7 改为：

```text
P4_RELEASE_CANDIDATE_LOCK
→ External Certification
→ P4_CERTIFIED_RELEASE_LOCK
```

### P3 可被跳过

v2.7 要求 P4 的每个 Workpack、Capsule 和 Gate 均绑定当前 `P3_BUILD_LOCK + C3_CHECKPOINT_PASS`。无 P3 模块时也必须生成经批准的 `P3_NOT_APPLICABLE_LOCK`。

### Codex Receipt 可自报

v2.7 不再接受只有 `runtime_session_ref` 的自报 receipt。可信调用证明必须由 Harness 外部的授权 Runner、Gateway 或 Lab Observer 采集，并绑定 challenge、调用事件和输出。

### 细节保真未进入外部认证

v2.7 将 `canonical_source_manifest`、`normative_atom_catalog` 和 `atom_coverage_matrix` 设为 Conformance Interface 的必需输入。

### Installed Harness 回到源码或执行包

v2.7 要求绝对入口、非 editable 安装、import origin、PATH/PYTHONPATH 快照和 source-shadow 检查。Build Program Driver 不能作为 Final Harness Runtime 的入口。

## 兼容处理

- 现有 v2.6 目标 Start Package 可以逐项迁移，不需要删除历史证据。
- 旧状态可保留为 `legacy_state`，但不能直接满足 v2.7 Gate。
- 缺少新字段时必须返回 `MIGRATION_REQUIRED`，不能静默填充 PASS。
- 迁移后应重新生成 Phase Lock、Pack Binding、Installed Target Descriptor 和 Certificate；旧 Certificate 不自动继承。
