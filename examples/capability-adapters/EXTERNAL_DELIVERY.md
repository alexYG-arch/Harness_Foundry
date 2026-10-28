# 外接能力交付与升级

此入口准备新的公开支持目录，不安装外包、不启动业务、不初始化项目、不授权。工程准备成功不等于目标 Harness 已验收。独立检查器、私有预期、账号凭据、旧报告及开发 `.venv` 不放入交付。使用者在项目现有说明中引用支持目录的 `AGENTS.md`，不覆盖项目已有指令。

## 交付

使用已选择且来源未变的宿主 materials：

```sh
"$PYTHON" examples/capability-adapters/delivery.py deliver --materials /host/materials.json --output /new/support
```

`PYTHON` 是本次明确绑定的 Python 3.11+。不要将私有 materials.json 交给生产者或目标。`delivery.json` 只记公开目录、外包/适配器版本、选用操作、工具要求及文件清单。原目录或 ZIP 的版本来源以目录清单身份记录，实际安装目录必须已通过现有 native 绑定；该入口不擅自下载或解压执行。原 ZIP 和原安装目录保留。

只有公开 Skill／资料而未选择原生调用的连接也会交付，标记 `CATALOG_ONLY`；不会猜测其可执行依赖。需要调用时先沿现有接口明确原生依赖并另存新交付。

外包放在 `external/<连接名>/upstream/`，适配器单独放置，许可证随选中的包保留。复制已绑定的运行/公开材料、原目录和必要链接目标；保留普通权限位及包内相对文件/目录链接。链接中 `..` 所需的目录也保留，不顺带复制目录内未选择文件。指向包外或绝对位置的链接需要明确的派生布局，不能在搬迁时悄悄改写。复制失败的部分目录保留，不称完成；改用新目录准备。不会把完整宿主材料当作外包。

内置能力位于 `builtin/`，公开文件复用上述布局复制：保留普通权限位、包内相对链接及必要链接目标，只复制已声明内容和必要路径，不顺带带入私有检查器或目录中的其他文件。内置清单保留原文件摘要，并记录各选择的 `layout`；仍按该能力的公开入口重建本机 profile。外接工具名保持原连接前缀，不覆盖内置同名工具。旧交付件不会被原地修补，需要另存新交付并验证实际入口。

选择 RSI 时另加 `--rsi-manifest /host/selected-rsi.json`，沿已有 `prepare_rsi_delivery` 清单交付选中的知识、Wiki／Reviewer／TDD 工具，并附 `rsi_handoff.py` 和交接说明。清单内知识路径相对于清单所在目录。修复流程在原有交回点使用这些工具，保持原任务身份、预算引用及事实/假设区分；没有知识命中不阻止任务。Reviewer 的实际运行仍由原宿主接收器、授权和预算负责，交付不创建新模型额度。

## 接收目录和新任务

新会话读取交付说明与所选 provider 的公开 Skill，使用新输入。先记录本项目工具，例如 `environment.json` 为 `{"node":{"path":"/declared/node"},"git":{"path":"/declared/git"}}`。按所选操作实际需要提供，不填写凭据。

```sh
"$PYTHON" support/examples/capability-adapters/delivery.py bind --delivery support --key instance.vendor --environment environment.json --project-root /target/project --output binding-new.json
"$PYTHON" support/examples/capability-adapters/delivery.py call --binding binding-new.json --operation echo --cwd /target/project -- example
```

`bind` 核对交付内容、版本、目录和工具，输出本机绑定；工具缺失保留 INCOMPLETE，不能凭文件存在宣称实际可用。`call` 只给出原 argv、资源要求和副作用说明。已有宿主执行器在原授权下实际调用并保存完整观察；外包仍拥有 Git、认证、上报、重试和更新语义。提供方的生命周期适配应保留原首次选择、已停用和已有配置处理顺序；连接/交付不自动启用已禁用项目。普通启动不重复 init、login 或上报。

调用前用已有 `native.attach_call` 绑定 CommandObservation；完整捕获后使用交付的 `native.py --recover <观察目录> --command-id <原ID> --executor LOCAL` 取回。取回不依赖当前外包是否仍存在，不执行 init/update/业务；部分捕获保持 UNRESOLVED，未知远端效果不得重试猜测。新查询或修后复验单独记录，不能混同旧报告取回。

## 升级和定制

每个新版本另存支持目录，重绑定实际选用的工具。`delivery.py compare --previous old-support --current new-support` 仅描述外部版本、内容和操作差异，不复制运行绑定、不转移授权、不改预算。原包更新使用原管理器；更新后按新实际版本重建材料、另存交付，旧报告和旧选择保留。断连只改未来选择，不删除旧报告或撤回远端效果。

Foundry 生成的连接/适配配置若已有项目定制，继续调用随交付提供的 `examples/harness-composition-upgrade/helpers/merge.py` 与 `apply.py`，逐文件列出真实 C（当前）、G（上次实际生成版本）、N（新生成版本），只包含 Foundry 拥有的文件。不将原包整体、外接包管理块、项目秘密或运行数据库纳入合并。无 G 保留 `PROJECT_INCREMENTAL_REQUIRED`，冲突先处理，不假造基线或静默覆盖。完整 apply 结果按已有恢复语义取回，不重放业务命令。换回旧依赖也是明确选择，不保证撤回已经发生的外部写入。

真实模型搭建、交付后新会话、自动修复触发及真实外部服务接收需要各自证据和运行范围。工程测试、帮助入口和静态交付不能代替这些结论。

## 功能级接入 v2 工程候选

本分支的 ALL / ON_DEMAND、决定复用、内外混用交付、接收绑定及报告入口见 [功能接入说明](FEATURES.md)。旧输入与旧包保留原语义；新版本和适用验证分列，不把候选材料记为部署或服务通过。
