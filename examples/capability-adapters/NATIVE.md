# 外部原生工具接入

此入口准备原工具调用，执行、授权、凭据和预算仍由现有宿主负责。原包保持独立版本。本发行只交付通用接口，不自带具体第三方提供方适配器。

## 准备和调用

先按 [CONNECTIONS.md](CONNECTIONS.md) 连接原目录或 ZIP。运行另给保持原布局和执行位的目录，准备器比较原件声明范围的文件集合和字节；未声明文件不因此成为必要依赖。准备阶段不运行安装、初始化、登录或上报。

下面的适配器仅示范字段；demo 原包和 tool.py 应由实际提供方交付，不能把示范当作已安装工具：

```json
{"provider":"demo","version":"1","package_versions":["1"],"runtime_files":[".codex-plugin/plugin.json","tool.py"],"operations":{"echo":{"argv":["tool:python","package:tool.py"],"tools":["python"],"effects":[]}}}
```

在已有 prepare.py 项目配置中增加：

```json
{
  "project_root": "/absolute/project",
  "connections": {
    "instance_root": "/absolute/foundry-instance",
    "native": [{
      "key": "instance.demo",
      "adapter_path": "/absolute/adapter.json",
      "root": "/absolute/provider",
      "operations": ["echo"],
      "environment_bindings": {"python": {"path": "/project/.venv/bin/python"}}
    }]
  }
}
```

已有 Plan 时沿原 workpack_ids 绑定公开材料。`consume.py --materials ... --tool instance.demo.echo -- ARGS` 返回原参数、cwd 和调用条件，不派发命令。第三方功能映射和裁剪使用 [FEATURES.md](FEATURES.md)；adapter_path 可在项目中单独维护，无需修改 Foundry 核心。

同名内部工具由连接身份区分，不改原工具名称或全局 PATH。子脚本依赖、动态库和缓存权限仍需显式准备并在实际接收器验证。路径存在不代表运行、服务或业务已经通过。

## 环境、生命周期和更新

原参数按声明交接；秘密使用原凭据库、宿主环境或 stdin，不写进准备 JSON、模型正文或 argv。生产模型、LOCAL 检查及外层宿主的凭据域分别处理；LOCAL 检查只支持其已声明的资源字段，不能据此声称支持任意插件登录环境。

提供方拥有原初始化、停用、项目选择、上报、重试和更新语义。通用连接不自动初始化项目，不重新启用已停用功能，不重复上报。需要专用生命周期交接时由提供方另行声明、实现和验证；本发行不替其补业务行为。

新版原包另存并重连，用 upgrade.py 从未展开的项目材料和完整新选择生成交接；外接独立使用可设 `selections: []`。同版本字节变化仍记录为来源变更。移除原生工具不删除仍需的资料、旧产物、报告或预算；完全断连后可回到原项目流程。定制文件使用现有 G/C/N 合并，见[包内升级工具说明](../harness-composition-upgrade/helpers/README.md)。

## 报告取回

可信宿主取得实际授权并创建原 CommandObservation 后，在派发前调用 `native.attach_call(observation, call)`。它只记录非秘密身份及参数摘要，不创建第二套 attempt、计数或批准。宿主实际执行一次，stdout/stderr 与完成结果沿原接收器记录和脱敏。

`native.recover_call(root, command_id, executor)` 取回原观察：完整捕获只读取；不完整为 UNRESOLVED，不重放、不探测当前版本、不重复扣额。CAPTURED 不等于成功或独立接受，仍核对原退出、业务回执和检查结果。清理由原资源生命周期负责，不删除提供方配置、认证或历史材料。
