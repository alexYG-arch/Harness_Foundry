# Foundry 发布准备与接入边界

更新：2026-09-21。当前产品版本 **0.2.0**，协议目标 **2.9**。
状态：**已批准的同包双案例最小端到端验收通过，发布收尾待远端执行**。
本页是用户说明，不签发运行授权或发布批准。精确范围见开发仓库在线
[发布说明](https://github.com/alexYG-arch/Harness_Foundry/blob/main/docs/releases/v0.2.0.md)及
[最终清单](https://github.com/alexYG-arch/Harness_Foundry/blob/main/docs/releases/v0.2.0-checklist.md)。
这些发布记录随源码公开，不是便携运行包的本地资源或运行依赖。

本日最新决定：用户要求停止维护旧新建流程。公开新建已统一为通用 Build，旧命令
明确退役而非兼容回退；旧数据以 `read-history` 只读，旧源码测试仅为历史基线。
通用包不包含旧 Producer/Validator/CLI；这不是宣称开发仓库已物理删除全部旧模块。

## 发布决定与分发形式

用户已确认：本项目采用 [MIT](../LICENSE)；唯一正式发布仓库为
[alexYG-arch/Harness_Foundry](https://github.com/alexYG-arch/Harness_Foundry)。
另一个历史远端不作为本轮正式发布目的地；本次没有修改远端、推送、打 tag 或发布。
许可正文采用 [OSI MIT 文本](https://opensource.org/license/mit)。

本轮按既定 **便携项目目录** 验收：把目录作为 Codex 工程打开，由其仓库 Skill 和
`tools/hffactory.py` 接入。暂不承诺 wheel、PyPI、插件或自动安装服务；`pip install`
仅用于开发依赖，不证明包中包含完整接入资源。最终候选应来自明确的干净提交，保存
并分发已验的同一份附件，不在验收后另行重打包替换。

MIT 不改变单独安装的 Python、Codex、可选依赖或外部规范/用户资料的许可。
便携包不复制 site-packages、模型、私人输入或 sibling 规范；历史源码诊断的外部规范
依赖不是当前通用运行依赖。已验附件为指定提交中的 35 个文件，含 MIT，无捆绑第三方
Python 依赖；原附件及清单保留，不在验收后重打包替换。

### 通用运行包的工程组装入口

在开发仓库执行 `python3 devtools/package_generic_release.py` 只做资源/依赖预检。
显式提供 `--output` 和已存在父目录下的绝对、尚不存在 ZIP 路径时，生成临时验收用
通用工程归档。它不是 Start Package Candidate，不创建 Program、目标或运行授权，
也不代表发布批准。实际发布仍要求后面的干净提交与同包双案例验收。

该组装器收集闭合的通用模块、公开合同、简短 Skill、接入说明及 MIT；不全量遍历旧
`src/` 或 `tools/`。归档没有旧 Candidate/媒体 Producer、Hash Store、sibling 规范、
作者运行库或凭据。通用控制库及 Codex 事件观察器已从旧实现抽离，旧源码 API 委托
同一份实现，不新增状态系统。只给最终归档一个 H1 摘要；模块清单不加逐文件 Hash。

`tests/test_generic_distribution.py` 在实际 ZIP 解压目录运行隔离 Python，验证全部模块
导入、CLI 编译/Review 门禁、临时提案到真实本地进程检查及不重放续跑、说明/Skill 链接、
版本来源和不可覆盖打包。测试 runner 不证明原生隔离或模型执行，不能作为正式端到端验收。

### 固定来源提交的候选组装

开发检查可读取工作区；待验发行候选必须显式选择提交：

```bash
python3 devtools/package_committed_release.py --revision <明确的提交或引用>
python3 devtools/package_committed_release.py --revision <同一提交> --output <尚不存在的绝对ZIP路径>
```

该开发工具将 Git 引用解析一次，从所选提交提取临时源码快照，运行该提交自己的组装器。
未提交/未跟踪文件及当前工作区的组装器不会混入归档，也不会修补提交内缺失的资源。
产品版本、协议版本和许可元数据从该源码核对；未知提交、缺资源或版本冲突均失败。
预检也会创建并清理临时源码，但不留下归档；输出分别报告临时写入与持久写入。
不改工作区、索引或提交，不创建 tag、不联网、不发布。Git 仅是开发组装依赖，不是包的运行依赖。

保存返回的 `source_revision`、唯一归档 H1 及原附件，后续双案例和发布消费同一份附件。
这只是来源固定机制，既不认证任意不可信 Git 提交，也不替代来源审查、干净版本记录或实际验收。
`tests/test_committed_distribution.py` 的提交全部位于临时测试仓库；其通过不代表当前未提交
修复已形成正式候选。真实来源提交、待验附件及检查结果以 Tracker 的最新记录为准；
固定来源和附件本身仍不是正式发布验收或上传授权。

## 当前可用与已验范围

2026-09-20 同包原生离线准备发现共享 `/tmp` 下只读夹具可写；同一接收器在系统用户
临时目录中的只读拒绝与声明写入对照通过。已增加 macOS 共享临时目录布局的运行前拒绝，
涵盖控制库、验收代码、来源、包及目标，不以更换位置假装修复底层平台问题。
参见 [目录适用性](GENERIC_BUILD_CLI.md#macos-原生运行的目录适用性)。
修正前的 58772ea 待验附件保留为历史，不得冒充修正后的发行物。

- 核心版本、声明编译、诊断和本地便携加载使用 Python 3.11+ 标准库。
- 通用 Build 消费已确认搭建文档，另行展示并批准具体执行范围；
  见 [Plan](GENERIC_BUILD_PLAN.md)、[CLI](GENERIC_BUILD_CLI.md)、
  [运行控制](GENERIC_BUILD_RUNTIME.md)及[合同对齐](ACCEPTANCE_CONTRACT_ALIGNMENT.md)。
- 在开发环境的 macOS / Python 3.13.3 / 原生 Codex GPT-6 Astra 上，M1 限定子流程
  已观察到建设 Harness、使用、耐久本地场景和完成后新 Codex 会话重入；各自经独立检查接受。
  B 会话内确实复现并修复缺陷；不能将其称为本轮控制器拒绝后再次派发的证明。
  旧失败历史保留。此结果不验收完整私有 PRD，也不证明当前发行包独立接入。
- 普通源码回归不运行模型。原生 OS 隔离、模型接收器、实际解释器及其依赖需在具体
  scope 内预检；Linux CI 通过不证明 macOS 原生执行通过，未验系统不声明支持。
- 2026-09-21，固定 `3c52c30` 包完成 Task CLI A1–A6 与 CSV B1–B5 的已批准最小方法。
  四个实际 Astra 会话分别建设和使用两例 Harness；25/13 组独立业务观察、内部/外部
  workdir 的 8/6 个项目测试、错误业务副本拒绝、预定故障撤除后复验与后继均通过。
  Task 在模型完成落盘后实际中断，新的宿主从同库恢复且 H 未重放。上游产物回退修复
  分支本轮未触发，其既有源码回归不冒称新增原生证明；不承诺任意故障自动恢复。

## 可公开复跑的源码检查

在含 `tests/` 的完整源码检出及已安装 `.[test,security]` 的 Python 开发环境运行
（不是在不带测试的便携目录里运行）：

```bash
python3 -B tools/check_release_source.py --report build/source-checks.json
```

report 文件必须不存在。该入口执行固定的通用输入/Review/计划/来源/控制/合同回归、
真实临时目录中的便携包迁移加载与文档资源检查，以及 Skill 检查。不借作者私有 Case、
运行库或规范 sibling；临时测试进程不是实际 Codex。必要模块缺失、零测试、失败、
跳过或 expected failure 均不能产生 `SOURCE_CHECKS_PASS`。本地/CI 共用这一入口。

它不是整包发布汇总：明确返回 `release_accepted=false`，保留未执行项。
全量兼容回归、物理 sibling 规范检查、原生运行及同包双案例仍须单独真实完成，
不能把这些必需义务改成 optional 来获得发布结论。工作流源码已提供；远端 Actions、
保护规则和公开平台运行结果只有实际执行后才能声明。源码测试失败返回工程修复，
不驱动目标模型猜测验收要求。

工作流的 Actions 版本及参数参照官方
[checkout](https://github.com/actions/checkout)、
[setup-python](https://github.com/actions/setup-python)、
[upload-artifact](https://github.com/actions/upload-artifact)；仅 `contents: read`，
不使用带特权的 PR target 触发、不保留 checkout 凭据，不传递模型账户凭据。

完整源码回归仍使用：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/hffactory.py verify-spec --json
python3 tools/validate_skill.py
python3 tools/hffactory.py validate-core --json
```

其中部分兼容回归和 `verify-spec` 仍依赖声明的只读 sibling。这是待退役的发行依赖，
不在无 sibling 的公开 CI 中伪造规范或将未执行报告为通过。19 项历史 opt-in 跳过
不得算原生验收证据；具体数量以本次完整日志为准。

## 最终发布剩余动作

本地已完成固定来源/附件、必要源码回归及同包双案例，已批准验收范围内未发现尚未解决的
交付缺陷。原义务没有靠改成 optional 闭合；各证据与未测边界见发布清单。

1. 保存发布说明/兼容性/支持边界与真实验收摘要的本地提交；核对待公开增量及原附件。
2. 获得针对正式仓库、版本、目标提交、原 ZIP 和所需设置的同一次明确发布授权。
3. 正常快进推送后核对相同发布提交的远端必需源码 CI；未执行、失败或跳过不能冒充通过。
   启用并核验非公开漏洞报告入口；无强推、历史改写或额外安全扫描矩阵。
4. 创建未冲突的 v0.2.0 tag 和 Release 草稿，上传已验原附件及单个归档校验值，再发布。
   下载核对同一 H1 并做 version/help 最小加载检查；不重跑昂贵模型案例。

已发布内容不覆盖修补、tag 不移动；后续修复发新版本。0.2.0 是实现版本，2.9 是协议目标，
不自动升级 3.0。任意未观测效果仍停止，回退不撤销副作用，不新增自动杀未知 PID 的承诺。

这些义务继续由现有工程 Tracker 管理，不新增数据库、认证链、每步骤批准或逐日志 Hash。
全部适用验收通过后再请求一次明确发布授权；获准发布后核对下载附件身份并做最小加载检查。

## 使用、反馈与安全限制

一般缺陷和改进建议在正式仓库的
[Issues](https://github.com/alexYG-arch/Harness_Foundry/issues)提出，附最小复现、版本、
预期/实际行为。提交测试或说明无需提交 `runs/`、数据库、原始会话、私人 PRD、凭据或用户数据。
不要在公开 Issue 披露未修复漏洞细节或密钥；2026-09-21 只读 API 核对确认私密漏洞
报告功能仍未开启。开启及核验纳入待确认的发布动作，不虚构邮箱、维护 SLA 或设置状态。
说明见开发仓库在线 [SECURITY.md](https://github.com/alexYG-arch/Harness_Foundry/blob/main/SECURITY.md)。
远端尚无 Release/tag/Actions 运行记录，不能宣称 CI 已通过。

支持承诺限定于发布说明中的环境与范围。升级使用独立目录并保留既有状态；不兼容库不得静默降级读取。
回退程序不撤销外部副作用，也不会恢复已撤销/过期授权。
