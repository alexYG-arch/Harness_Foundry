# v2.7 → v2.8 迁移映射

## 1. 迁移目标

v2.8 保留 v2.7 的 Authoring/Execution 隔离、阶段锁、三工程独立性、安装来源和外部认证边界，并补齐批准之后的机器控制平面。

迁移不是把 `auto_start_generated_workpacks` 改为 `true`。合法迁移必须维持：

```text
Authoring Candidate
→ Human Review / Charter and Profile Locks
→ Registration Only
→ bounded Execution Authorization
→ Controlled Automatic Progression
→ hard stop or Certified Release
→ separate Real Target Install Authorization
```

## 2. 核心映射

| v2.7 状态 | v2.8 迁移 | 目的 |
|---|---|---|
| 三工程顺序仅在 Markdown | `THREE_PROJECT_PROGRAM_MANIFEST` + `ENGINEERING_PROJECT_DAG` | 机器选择工程 bootstrap、build、install 和 barrier |
| G0–P4 Phase Manifest | 保留并接入 Program Driver State | 防跳阶段并支持断点恢复 |
| 发布链主要在 Markdown | `RELEASE_PIPELINE_MANIFEST` | 明确 A/B0/C/Build/B1/Installability/D/C4 的状态、证据和重入 |
| Workpack PASS 不可连续推进 | 有效授权下由 Driver 选择唯一下一 Workpack | 连续推进仍受 one-active-workpack 和 Gate 限制 |
| R/F 最大轮数仅为文字要求 | `LOOP_POLICY` + `LOOP_STATE` | 轮次、振荡、停止和升级可机读 |
| Finding/Repair 仅为规范 | Finding Schema、Routing、Invalidation DAG、Reentry Plan | 自动失效、单一修复 Owner 和正确重入 |
| Command Manifest 字段不足 | 绝对 executable、authorization、exit/evidence、idempotency | 安全调度并支持 crash recovery |
| 只有三个工程角色引用 | 完整角色、独立工程 Start Package | 闭合 Driver、Runner、Installer 和 Gate 权限 |
| 真实安装需另行授权 | 继续保留独立授权 | 防止自动控制层越权影响真实环境 |

## 3. 不能继承的状态

以下 v2.7 状态不能直接升级为 v2.8 自动化就绪：

- 只有 `START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW`；
- 只有 Phase Graph，没有三工程 DAG；
- 只有 A/B0/C/B1/D 文档顺序，没有 Release Pipeline State；
- 只有 Workpack 列表，没有 Driver、Authorization、Loop 和 Recovery；
- 只有 Finding 描述，没有机器失效和重入资产；
- 使用非绝对命令入口或缺少执行授权引用；
- Lab/Linkage 只有角色名称，没有独立 Start Package、构建和安装计划。

缺失任一项时必须返回 `V28_CONTROL_PLANE_MIGRATION_REQUIRED`。

## 4. 迁移后的合法初始状态

迁移完成的目标包仍必须以 Authoring 状态交付：

```text
execution_mode = AUTHORING_ONLY
auto_start_generated_workpacks = false
controlled_auto_progress_ready = false
next_eligible_transition = HUMAN_REVIEW_OF_START_PACKAGE
```

只有批准、锁定、Registration 和 `EXECUTION_AUTHORIZATION` 校验完成后，Driver 才能将运行时状态提升为 `AUTHORIZED_READY`。

## 5. 重验要求

迁移后至少重验：

1. 所有 JSON/JSONL、相对链接和角色引用；
2. 三工程 DAG 拓扑、版本兼容和 barrier；
3. P3 正常与 N/A 两条合法边，以及跳 P3 负例；
4. 发布链的唯一 next action 和无循环性；
5. 无授权、过期授权、权限扩大和真实安装越权负例；
6. loop 最大轮数、重复 Finding、振荡和 resume token；
7. Driver 在提交前/提交后崩溃的幂等恢复；
8. 上游变化触发跨三工程的 invalidation 和最早重入。

历史 v2.7 证据可作为审计输入，但不能自动满足新的控制平面 Gate。
