# Three Project Start Package Templates

本目录提供三个相互独立的工程启动模板：

1. `external_lab/`：先构建、负向自校验并发布独立 Lab 工具；
2. `linkage_review/`：在 Lab 接口锁定后构建、只读自校验并发布 Linkage 工具；
3. `main_build/`：在两套工具版本兼容并登记后物化 Main Execution Package，按 G0–P4 构建 Harness。

上面的编号是 `ENGINEERING_PROJECT_DAG.json` 的默认有向顺序，不是依赖目录名猜测。实际推进还必须满足 Human Approval、Shared Baseline、Driver Runtime Verification 和 Execution Authorization。

每个子目录均包含：

- `PROJECT_CHARTER.template.md`；
- `PROJECT_STATE.template.json`；
- `WORKPACK_INDEX.template.json`；
- `COMMAND_MANIFEST.template.json`；
- `BUILD_INSTALL_PLAN.template.md`；
- 子目录 `README.md`。

## 使用边界

- Authoring 只实例化模板，三个工程初始均为 `PLANNED_NOT_STARTED` 或等待批准状态。
- 三个工程必须使用不同 project root、Candidate Workspace、分发包、安装环境和写权限。
- Lab 和 Linkage 的安装是工具安装，不是 Main Harness 安装。
- Linkage 永远只读；Lab 可以签发 Certificate，但不能修复 Main；Main 不能自我认证。
- Certification Installer 是环境变更的唯一 Owner。
- 真实目标安装不在任何子工程普通 Command Manifest 中，必须使用独立授权。
