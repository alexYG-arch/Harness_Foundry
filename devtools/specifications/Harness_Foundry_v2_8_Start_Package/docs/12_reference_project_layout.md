# 参考工程布局

## 1. 本指导包

```text
Harness_Foundry_v2_8_Start_Package/
├── README.md
├── START_HERE.md
├── DOC_INDEX.md
├── PACKAGE_MANIFEST.json
├── MIGRATION_MAP_v2_6_to_v2_7.md
├── docs/
├── prompts/
├── templates/
├── tools/
├── tests/
└── checklists/
```

它只指导模型编写目标 Start Package，不承载目标 Harness 代码、Release 或 Certificate。

## 2. 模型应生成的目标 Start Package

```text
<target>_Harness_Charter_Start_Package_v0_1/
├── README.md
├── START_HERE.md
├── START.md
├── PACKAGE_MANIFEST.json
├── START_CONTEXT.json
├── PACKAGE_ROLES.json
├── PROGRAM_CHARTER.md
├── TARGET_PROFILE.md
├── PROFILE_LOCK.json
├── CHARTER_LOCK.json
├── AUTHORITY_AND_EXECUTION_BOUNDARY.md
├── PROGRAM_STATE.json
├── PHASE_DEPENDENCY_MANIFEST.json
├── PHASE_TRANSITION_LEDGER.jsonl
├── THREE_PROJECT_PROGRAM_MANIFEST.json
├── ENGINEERING_PROJECT_DAG.json
├── RELEASE_PIPELINE_MANIFEST.json
├── PROGRAM_DRIVER_CONTRACT.json
├── PROGRAM_DRIVER_STATE.json
├── PROGRAM_AUTOMATION_POLICY.json
├── AUTHORIZATION_POLICY.json
├── EXECUTION_AUTHORIZATION.json
├── LOOP_POLICY.json
├── LOOP_STATE.json
├── FINDING_SCHEMA.json
├── REPAIR_ROUTING_RULES.json
├── INVALIDATION_DAG.json
├── REENTRY_PLAN.json
├── USER_ADJUSTMENT_RECORD.json
├── AUTHORING_HANDOFF.md
├── canonical_sources/
│   ├── SOURCE_MANIFEST.json
│   ├── NORMATIVE_ATOM_CATALOG.json
│   └── ATOM_COVERAGE_MATRIX.json
├── planning/
│   ├── ROADMAP.md
│   └── WORKPACK_INDEX.json
├── contracts/
│   ├── ARTIFACT_AND_INTERFACE_CONTRACTS.md
│   └── VALIDATION_AND_REVIEW_PLAN.md
├── constitution/
├── phases/
│   ├── G0/
│   ├── P1/
│   ├── P2/
│   ├── P3/
│   └── P4/
├── workpacks/
├── commands/
├── capsules/
├── schemas/
├── build_program/
│   └── conformance/
├── conformance_pack/
├── linkage/
├── installation/
├── project_start_packages/
│   ├── main_build/
│   ├── external_lab/
│   └── linkage_review/
└── validation/
```

这是初始工程控制包，不是已经完成的 Harness。它可以携带 schema、validator 规格和首批 Workpack，但不能凭目录存在宣称实现完成。

这些根级机器 JSON/JSONL 是批准后 Driver 的控制输入；Authoring 交付时全部 execution state 仍为 false。三个 `project_start_packages/` 分别控制自身工程，不能合并成一个可互相越权的工作区。

## 3. Coding 后形成的 Main Harness 工程

```text
main_harness_project/
├── repository/                 # 最终产品源码
├── build_program/              # 建设控制、Workpack、证据
├── dist/                       # Release Candidate Artifact
└── evidence/
```

必须存在两个不同入口：

```text
Build Program Driver   # 只推进工程建设
Final Harness Runtime # 只运行已安装 Harness 的业务 Run Path
```

## 4. 两个外部工程

```text
foundry_conformance_lab/
├── pyproject.toml
├── src/
├── tests/
└── dist/

conformance_linkage_review/
├── pyproject.toml
├── src/
├── tests/
└── dist/
```

- Lab 拥有权威 checker、scenario runner、attestation observer 和 Certificate Builder。
- Linkage 是只读工程，不安装、不修复、不发 Certificate。
- Harness-specific Pack 是声明式输入；不允许其 parser 取代 Lab 的权威解析。

## 5. 三种安装环境

```text
P4_INSTALLABILITY_ENV    # Candidate 前验证可安装性，完成后销毁
SINGLE_CERTIFICATION_ENV # 唯一 Certification Installer 创建，D/C4 共用
REAL_TARGET_ENV          # Certificate 后单独授权安装
```

三个环境的 Receipt、路径、Hash 和生命周期不得混用。

## 6. 控制面与产品面分离

```text
Foundry Program Driver / ledgers / authorization  # 工程建设控制面
Main Harness installed distribution               # 最终产品运行面
Lab and Linkage installed distributions           # 独立校验工具面
```

最终 Harness 入口不得导入控制面；Driver 也不得把自身入口写入 Installed Target Descriptor。自动推进只改变建设控制状态，不将 Start Package 变成最终 Harness 安装源。
