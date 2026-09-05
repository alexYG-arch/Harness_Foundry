# Foundry epoch 24 源码修复记录

日期：2026-09-05。状态：`SOURCE_REPAIR_AND_REGRESSION_PASS / AWAIT_EXPLICIT_REOPEN`。范围：用户授权的六项 Producer / Validator 修复、回归及内部验证；停止于 REOPEN 前。

## 边界与保持项

- Program：`PROGRAM-GITHUB-SKILL-VIDEO-EXPLAINER-HARNESS-V1`；epoch 24、revision 157、`FROZEN`、`CANDIDATE_READY_FOR_HUMAN_REVIEW`。
- 没有修改既有 Candidate、冻结 Requirement、SQLite 或源快照；没有 REOPEN、Freeze、Generate、Candidate 批准、Execution Root 创建、目标 Workpack / Driver / Harness 执行、模型下载或媒体生成。
- 保留本轮开始前的未提交与未跟踪修改。本轮修改的生产文件为 `semantic_contracts.py`、`validator.py`、`invariant_contracts.py`、`mutation_contracts.py`；新增 `media_evidence_contracts.py`、本记录和 `test_epoch24_semantic_repairs.py`。
- 一 Skill 一支约三分钟视频、本地开源 TTS、本地动画、同步与功能/场景/效果证据要求、目标 Skill 执行默认关闭均不变。
- Foundry、Karpathy、HERO 约束用于保持修复范围：先复现正常路径及错误关联，再修 Producer 与独立检查；没有增加审批环、签名体系、hash 台账、全字段 fuzz 或新依赖。

## 六项修复与对应证据

| 问题 | Producer 修复 | 独立检查与行为回归 |
|---|---|---|
| Motion 非零阈值被两个相同操作数遮蔽 | `changed_frame_count > 0` 仅生成一个逐对象操作数 | 正数通过；首/尾零值拒绝；解释器及 Validator 拒绝二操作数与 threshold 并存 |
| 拒绝分支运行授权专用谓词 | 七个授权谓词选择 `AUTHORIZED_EXECUTION_RECEIPT_VALID`；负例基线同步选择同一分支 | `DENIED_NO_SIDE_EFFECT` 的 nullable 字段不会进入授权谓词；授权分支仍检查真实字节与摘要；错误分支投影拒绝 |
| Render 资产内容谓词退化为重复文件 hash 谓词 | `RENDER_INPUT_ASSET_SET_EQUALITY_V1` 比较 manifest 与 asset plan 的资产 ref/digest 集合；原文件字节谓词保留 | 正确集合及重排通过；缺项、重复、空集合和错 digest 拒绝；引用 JSON 的成员 mutation 后重算 manifest 文件摘要，资产关系失败而文件字节谓词通过 |
| FFprobe 未读取被测视频身份 | `REFERENCED_JSON_FIELD_EQUALITY_V1` 读取 receipt 内 `/input_sha256` 与 `video_sha256` 比较 | 相同输入通过；其他视频或缺失身份不通过；旧 hash-only 投影及错误 JSON 字段被独立 Validator 拒绝 |
| TTS 文件摘要与视频内音频包摘要混用 | `AUDIO_FILE_PACKET_LINEAGE_V2` 保留 `audio_sha256` 的完整源文件含义；在已有 render command receipt 绑定编码变换与 packet digest | COPY / TRANSCODE 参考模型正例通过；错误源、视频、packet digest 或重放包拒绝；缺少提取/重放回调是 INCONCLUSIVE，不冒充 PASS |
| 公共入口排除仓库根 SKILL.md | 可选目录前缀 | 根与嵌套 SKILL.md 通过；绝对路径、父目录穿越、非 SKILL.md 拒绝；独立接口检查包含正常根入口 |

### 组合与旧输入重编译

旧生成投影不能覆盖修复后的算法。仅迁移已识别的旧 hash-only、旧音频算法、重复 Motion 操作数形状及授权分支投影；不建立通用迁移框架，也不丢弃任意未知语义覆盖。

新增测试覆盖：旧形状输入不被就地修改、重编译生成当前投影、再次编译保持一致。授权分支修复的组合回归还复现了负例基线仍为 `ANY_PASSING_BRANCH` 的同族缺口；Producer 的 mutation recipe 现在采用谓词分支，独立 Registry Validator 同时核对 recipe 与 Case 基线。

### 音频证据接口及成本边界

`media_evidence_contracts.py` 是纯参考实现：调用方提供 resolver 与音频提取/重放函数；该文件不调用 shell、FFmpeg、TTS 或网络，也不写文件。测试使用明确标记的内存字节与回调，不是实际编码证据。

已有 `render_command_receipt_ref` 指向的 JSON 使用 `audio_transform` 对象，包含：

- `input_audio_ref`、`input_audio_sha256`：输入的完整 TTS 音频文件及摘要。
- `output_video_ref`：这次变换所属的最终视频。
- `packet_payload_sha256`：所选音轨按 demux 顺序连接 payload 后的摘要；排除容器和时间戳，不与完整源文件摘要比较。
- `mode`：`COPY` 或 `TRANSCODE`。
- `encoder_parameters`：可独立复现的准确编码器版本、codec、filter、时间与重采样参数；COPY 路径提取源包，TRANSCODE 路径从源音频重放。

实际 Lab 实现必须独立读取最终视频包并验证从该源产生的结果，不能把 Producer 自报 packet digest 当作声音内容证明。只有回调存在及返回字节不代表其真实实现已经认证。外部编码器是否可重复、参数是否完整、实际音轨质量和同步仍须后续获授权运行时验证。

不声称本轮降低了全产品 hash 成本。packet 身份用于替代错误的跨字节域比较，并复用现有 receipt；没有新增顶层重复账本。TRANSCODE 重放有计算成本，本轮没有执行或测量它，也没有把成本隐藏在“静态校验通过”中。

### Negative evidence 边界

`prepare_referenced_document_mutation` 返回内存文档和引用字节 overlay，不修改原文件。回归独立证明 Render 内容关系与 manifest 字节关系可分离。

这不等于完整 Render artifact 已通过全部外部 Oracle，也不等于所有逐 invariant 负例已被实际执行。Registry 仍要求完整 schema 通过、目标 invariant 失败、其他 invariant 通过；找不到精确反例、缺少证据、超时或 runner error 不算通过。不通过放宽 Validator 闭合。

## 验证记录

- 第一批 9 项测试产生 15 个失败子断言，复现六项已知缺陷；修复后通过。
- 补充独立 Validator、COPY、集合重排、旧形状重编译与分支负例基线后，新增模块共 18 tests / OK。
- 既有语义生产、typed kernel、公共 Job、mutation 与生成谓词组合共 96 tests / OK（首轮 80.078 秒）。
- epoch 24 冻结 Requirement 的只读内存重编译：74 artifacts、166 唯一 kind/invariant；66 typed kernel、100 external exact algorithm；Producer findings 0、独立 invariant findings 0，Registry 独立一致，重编译幂等。该探针不生成或替换 Candidate。
- 最终源码全仓命令 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v`：434 tests，384.727 秒，OK，退出码 0。此前中间源码的 433 tests / OK 不代替此最终结果。
- `python3 tools/hffactory.py verify-spec --json`：PASS，101 个文件，writes_performed=false。
- `python3 tools/validate_skill.py`：PASS，writes_performed=false。
- `python3 tools/hffactory.py validate-core --json`：PASS，41 项能力、26 个 selector results、0 findings，writes_performed=false，未创建 Candidate 或 Execution Root。
- `git diff --check`：通过。
- 真实 CLI `status`、`readback` 与 `verify-run` 只读复核：revision 157、event_count 157、FROZEN、Human approval PENDING、execution_started=false、execution_root=null。状态、冻结 Requirement 与 Candidate 绑定保持本轮开始时的值。读取到的既有 Candidate validation_report 是历史生成记录，不把它冒充修复后的新 Candidate 验证结果。

## 下一真实 gate

源码修复不自动升级 epoch 24 Candidate。需要用户另行显式 REOPEN epoch 24 并绑定新的绝对空 output root；本次授权不包含这一步。旧 Freeze / Generate 授权不沿用。
