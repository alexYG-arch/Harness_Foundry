# Target Start Package Templates

这些模板用于创建某个具体 Agent/Harness 的初始宪章 Start Execution Package，以及批准后供 Program Driver 消费的受控自动推进控制面。

## 使用规则

1. 复制模板结构到新的目标目录，不要覆盖本指导包。
2. 把 `<...>` 替换为来自用户资料或明确决定的值。
3. 不得通过删除字段绕过未决问题；未知值应显式标记 `TBD_REQUIRES_HUMAN_DECISION`。
4. JSON 模板必须保持可解析。
5. 模板产物是 Candidate；人类批准和 Lock 之前不授权 Coding。
6. `auto_start_generated_workpacks=false` 是 Authoring 默认值；不得为实现自动化而改成自启动。
7. 三个工程的独立模板位于 `../project_start_packages/`，必须与本目录控制面共同实例化。

## 模板清单

- `START_CONTEXT.template.json`
- `TARGET_README.template.md`
- `START_HERE.template.md`
- `START.template.md`
- `TARGET_PACKAGE_MANIFEST.template.json`
- `PACKAGE_ROLES.template.json`
- `PROGRAM_CHARTER.template.md`
- `TARGET_PROFILE.template.md`
- `PROFILE_LOCK.template.json`
- `CHARTER_LOCK.template.json`
- `PROGRAM_STATE.template.json`
- `PHASE_DEPENDENCY_MANIFEST.template.json`
- `PHASE_TRANSITION_LEDGER.template.jsonl`
- `THREE_PROJECT_PROGRAM_MANIFEST.template.json`
- `ENGINEERING_PROJECT_DAG.template.json`
- `RELEASE_PIPELINE_MANIFEST.template.json`
- `PROGRAM_DRIVER_CONTRACT.template.json`
- `PROGRAM_DRIVER_STATE.template.json`
- `PROGRAM_AUTOMATION_POLICY.template.json`
- `AUTHORIZATION_POLICY.template.json`
- `EXECUTION_AUTHORIZATION.template.json`
- `REAL_TARGET_INSTALL_AUTHORIZATION.template.json`
- `LOOP_POLICY.template.json`
- `LOOP_STATE.template.json`
- `WORKPACK_RESULT.template.json`
- `FINDING_SCHEMA.template.json`
- `REPAIR_ROUTING_RULES.template.json`
- `INVALIDATION_DAG.template.json`
- `REENTRY_PLAN.template.json`
- `PROMOTION_LEDGER.template.jsonl`
- `REVOCATION_LEDGER.template.jsonl`
- `CANONICAL_SOURCE_MANIFEST.template.json`
- `NORMATIVE_ATOM_CATALOG.template.json`
- `ATOM_COVERAGE_MATRIX.template.json`
- `USER_ADJUSTMENT_RECORD.template.json`
- `AUTHORITY_AND_EXECUTION_BOUNDARY.template.md`
- `ROADMAP.template.md`
- `WORKPACK_INDEX.template.json`
- `WORKPACK.template.md`
- `CAPSULE.template.json`
- `COMMAND_MANIFEST.template.json`
- `ARTIFACT_AND_INTERFACE_CONTRACTS.template.md`
- `VALIDATION_AND_REVIEW_PLAN.template.md`
- `CONFORMANCE_INTERFACE.template.json`
- `RUNTIME_ATTESTATION_POLICY.template.json`
- `INSTALLED_TARGET_DESCRIPTOR.template.json`
- `P4_BUILD_INPUT_LOCK.template.json`
- `RELEASE_CANDIDATE_LOCK.template.json`
- `CERTIFIED_RELEASE_LOCK.template.json`
- `START_PACKAGE_VALIDATION_REPORT.template.json`
- `AUTHORING_HANDOFF.template.md`
