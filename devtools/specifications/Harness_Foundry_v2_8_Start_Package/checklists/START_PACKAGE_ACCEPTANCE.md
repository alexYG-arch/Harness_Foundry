# Target Start Package 验收清单

## A. 定位与边界

- [ ] 明确目标包是工程 Authoring/Execution Start Package，不是 Harness Release。
- [ ] 明确 Build Program Driver 与 Final Harness Runtime 是两个入口。
- [ ] 明确 Pack 不是 Certificate，Linkage PASS 不是 Certification PASS。
- [ ] `auto_start_generated_workpacks=false`。

## B. Canonical Source 与细节保真

- [ ] 所有用户指定资料进入 Source Manifest 并绑定 Hash。
- [ ] 每个规范 Atom 有 source locator、Authority、verification mode。
- [ ] 单位、顺序、否定、默认值、错误、取消、重试、超时、兼容性和非目标未被丢失。
- [ ] Atom → Workpack → Stage → Scenario → Assertion → Evidence 正向覆盖。
- [ ] 实现/输出字段可反向映射到 Atom 或 Finding。

## C. 阶段状态机

- [ ] Profile 已锁定，禁止为通过 Gate 事后降级。
- [ ] G0/P1/P2/P3/P4 和 C0-C4 前驱关系机器可读。
- [ ] P4 明确依赖当前 `P3_BUILD_LOCK + C3_CHECKPOINT_PASS`。
- [ ] P3 不适用时需要 `P3_NOT_APPLICABLE_LOCK`，不能直接跳过。
- [ ] `highest_touched_phase` 与 `highest_locally_closed_phase` 分离。
- [ ] Transition Ledger 为 append-only，并绑定前驱 Hash。

## D. Workpack 与命令

- [ ] 每个 Workpack 只有一个 primary layer 和明确范围。
- [ ] Allowed/Forbidden Write Paths、Required Inputs/Outputs 完整。
- [ ] Command Manifest 使用 argv 数组和统一 workspace root anchor。
- [ ] `cwd` 后的相对路径没有重复根目录。
- [ ] Authoring/Registration 不可执行生成 Workpack、安装或启动。

## E. Runtime 与 Codex/LLM 调用证明

- [ ] Runtime Ownership 和 missing-runtime gate 已定义。
- [ ] Codex/LLM receipt 不能由 Harness 自报即通过。
- [ ] Attestation 绑定 challenge、真实 executor、run/stage/release/environment、输入输出和 raw trace。
- [ ] 包含伪造、重放、输出替换、stub executor 负例。

## F. Conformance 与安装

- [ ] Main、External Lab、Read-only Linkage 的职责和写权限分离。
- [ ] Pack 为声明式输入，权威 parser/checker 归 Lab。
- [ ] B0、Package Build、B1 顺序明确。
- [ ] Candidate Lock 与 Certified Lock 分离。
- [ ] Build Install Test、Certification、Real Target 三环境及 owner 分离。
- [ ] Installed Target Descriptor 验证绝对入口、非 editable install、import origin 和 source shadow。

## G. 必杀负例

- [ ] 缺 P3 Lock 直接 P4 必须失败。
- [ ] 旧 P2/P3 Hash、伪造 Lock、乱序 Transition 必须失败。
- [ ] 最终产物缺中间 Stage Receipt 必须失败。
- [ ] 从源码树或 Build Program Driver 启动必须失败。
- [ ] 删除或歪曲任一 Required Intent Atom 必须失败。
- [ ] 修改 checker/scenario 后复用旧 Certificate 必须失败。

## H. Authoring 停点

- [ ] 只允许终态 `START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW`。
- [ ] `AUTHORING_HANDOFF.md` 列出未决问题、首个 Workpack 与启动 Gate。
- [ ] 未经人类批准不得生成 Charter Lock、启动 G0 或执行任何命令。

## I. 受控自动推进控制面

- [ ] 三工程 Program Manifest、机器 DAG、项目状态和兼容 barrier 完整。
- [ ] Main、External Lab、Read-only Linkage 各自有独立 Charter、Workpack、Command 和 Build/Install Plan。
- [ ] Program Driver 能从机器状态求出零个或一个 `next_action`；多个候选必须阻断。
- [ ] Release Pipeline 逐项表达 A/B0/C/Build/B1/Installability/Candidate/Certification Install/D/C4。
- [ ] Program Automation Policy 区分可自动节点、需授权节点和永远人工节点。
- [ ] Execution Authorization 绑定模式、工程、Workpack/Gate、命令、路径、环境、有效期、最大步数和副作用。
- [ ] Loop Policy/State 定义最大轮次、Finding 指纹、振荡、收敛、停止、升级和 resume。
- [ ] Finding、Repair Routing、Invalidation DAG、Reentry Plan 和 Revocation Ledger 可机读。
- [ ] Driver 具备 lease、idempotency key、原子提交、重复命令拒绝和 crash recovery 契约。
- [ ] `PROGRAM_STATE` 包含 current/next phase、有效/失效锁、blocker、授权和 loop 引用。
- [ ] Command Manifest 使用绝对 executable、argv 数组、Authorization、期望退出码和 stdout/stderr evidence。
- [ ] Authoring Review、P3 N/A、设计权威变化、权限扩大、循环升级和真实目标安装均为硬停点。

## J. 自动化负向验收

- [ ] 无授权、过期授权、授权 scope 不匹配时不得执行。
- [ ] 同时出现两个 next action、两个 active Workpack 或 lease 冲突时不得猜测推进。
- [ ] P3 缺失或 N/A 未经批准时不得进入 P4。
- [ ] A/B0/C/B1/D 任一缺失时不得压缩跳到 C4。
- [ ] 重复 Finding、无进展轮次或 A↔B 振荡必须升级并停止。
- [ ] Driver 在命令完成但状态未提交时重启，不得重复产生副作用。
- [ ] 上游 Hash 变化必须使三个工程的受影响状态和发布链自动失效。
- [ ] 任何自动尝试 `REAL_TARGET_INSTALL` 都必须返回硬拒绝。
