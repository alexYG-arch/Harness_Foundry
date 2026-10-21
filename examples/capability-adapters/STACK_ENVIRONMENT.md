# 按需技术栈环境接入

这组可选工具把所选环境的发现、配置、真实调用和报告交接放进能力包。原宿主仍执行明确命令并管理权限、预算、修复和清理。包不安装工具，不修改全局环境，不自动重试，也不增加必经预检。没有选择环境包的项目继续使用原路径。

当前首批是 QtCore/CMake 的 `qt-cmake@2` 和 Python 的 `python-environment@1`。包内 guide 给出各操作参数。包版本、下面的材料格式版本1、实际SDK/工具版本分别记录；协议保持2.9、Plan保持1.2。这不是新的Plan字段或环境管理器。

## 三份材料怎样交接

| 材料 | 写入者和内容 | 读取及边界 |
|---|---|---|
| 环境 profile | 包的纯 discover/bind，或显式观察命令另存结果；工具角色、调用路径、必要参数、所选文件身份 | prepare、所选启动器和保护检查器；不是授权或环境PASS |
| 命令捕获及探测报告 | 启动器记录单次argv/cwd/时间/退出码/stdout/stderr；栈检查记录实际结果、模块/SDK及覆盖范围 | 宿主归档；完整捕获只读取，不重放。缺附件、未知完成或清理未解决保持未知 |
| 公开交付清单 | stack_handoff.deliver按选版收集公开文件、相对路径及依赖声明 | 目标重新绑定本机环境；不含私有checker、独立预期、旧本机profile或完整宿主materials |

profile必需字段：`kind: stack-environment-profile`、`format_version: 1`、`package.name/version`、`platform.system/machine`、非空`tools`角色到绝对调用路径、`environment`、`operations`、`observations`。`read_paths`和`extensions`由所选操作按需提供；prepare将显式读取根映射到现有scope片段，不能靠profile扩权。读取器仅支持格式1；不把未知新格式猜成兼容。旧的无profile材料保持原语义。

`environment.set`对选定键赋值，`prepend`按给定顺序前置路径并保留继承值后缀；同一个键不能同时使用两种操作。配置只记录非秘密值，不快照整个父环境。工具原生Preset/命令行仍有自己的优先关系，具体见Qt guide；不能用两份profile相同推定实际子进程相同。

`observations`观察明确文件，不遍历SDK/环境目录。保留入口与真实目标，尤其不把两个venv因系统解释器相同而合并。版本字符串及查询证据由实际观察提供，prepare本身不调用`--version`。`read_paths`不是安装清单；包、项目配置和SDK各自维护。

原生依赖观察还记录实际选中加载路径经过的链接及其真实目标，存入 `extensions.path_aliases`；需要读取链接的父目录作为 `read_paths` 提案。只沿这些路径观察，不扫描安装目录。当前 macOS 接收器中，精确链接权限可能被规范化，读取链接元数据需要其真实父目录；这会使父目录名称和链接元数据可见，不能描述成只读单个链接。该提案必须通过现有 scope/Readback 明确接入，不能自行扩权；其他未声明库是否仍不可读需要实际接收器验证。证据复用时重新核对已记录链接，换目标要求局部复验，无法读取保持 UNKNOWN。

声明工具文件还不等于其启动依赖齐全。若工具是转发启动器，保留实际错误，显式选择并绑定已安装的真实工具，或声明其所需启动依赖；不要根据报错猜路径、开放整个 SDK 或自动安装。新目录的 observe 与 probe 都须在对应已声明条件下实跑。

## 完整双栈准备例

先按各包guide生成新的Qt与Python profile。Qt的辅助解释器用`qt-python`，项目解释器用`project-python`，允许不同venv。下面是填写模板，所有路径及版本都需替换成实际观察；不是可直接执行的本机配置：

```json
{
  "project_root": "/host/project",
  "selections": [
    {"directory": "/host/packages/qt-cmake-2", "version": "2", "environment_profile": "/host/config/qt-observed.json", "workpack_ids": ["BUILD"]},
    {"directory": "/host/packages/python-environment-1", "version": "1", "environment_profile": "/host/config/python-observed.json", "workpack_ids": ["BUILD"]}
  ],
  "environment_bindings": {
    "qt-python": {"path": "/host/helper-venv/bin/python", "observed_version": "3.14.5"},
    "project-python": {"path": "/host/project-venv/bin/python", "observed_version": "3.14.5"},
    "cmake": {"path": "/host/cmake/bin/cmake", "observed_version": "3.31.12"},
    "ctest": {"path": "/host/cmake/bin/ctest", "observed_version": "3.31.12"},
    "qt-sdk": {"path": "/host/qt-sdk"}
  }
}
```

调用原`prepare.py --config CONFIG --output NEW`生成新材料。`selection.environment_profile`必须对应包的相同名称/版本，其工具绑定不能与显式项目绑定矛盾。调用前`check_selection`核对包和本机profile仍对应保存来源；材料READY仅证明可交接。

`stack_handoff.py call --materials MATERIALS --tool qt-environment -- probe --work-dir NEW --report-dir NEW --receiver ID`生成显式argv，自动在子命令之后加入绑定profile；不会启动进程。Python对应`--tool python-environment -- run --cwd PROJECT --report-dir NEW --module-name project_package.cli -- --input INPUT`。业务`--`之后的参数仍归业务，包括业务自己名为`--profile`的参数。原`consume.py`继续支持普通无profile工具。

宿主把`preparation.verifier_inputs`对应文件复制到原verification_root，并将`checker_files_fragment`合入既有资源。公开helper/profile可以`shared:true`，独立预期和判定代码不能共享。真正检查必须从受保护副本加载。生产与检查可以使用同字节公开配置，但各自读写域及私有预期不同，真实探测分别留证。

实际命令使用现有LOCAL或已授权宿主；普通有限启动器只封装一个所选命令，不管理Program或attempt。Qt probe是明确的configure/build/CTest/CLI四个阶段，每次命令分别捕获；先前阶段失败即返回，不隐藏重试。900秒为单个命令默认值，外层命令可以有更严格整体预算。超时只清理本次子进程组，清理失败有界返回，不能声称已清理或重新派发。

## 修后准备、复用和公开交付

修正配置后，使用`upgrade.py`与当前有效项目基础材料及完整选择另存新材料。旧扩展材料仅作为previous对照，不把旧INCOMPLETE材料继续叠加成READY。包版本不变也可合法更新环境绑定；旧诊断与累计预算保留。材料重准备不执行apply、不继承运行批准或接受。实际目标普通文件继续用原C/G/N合并，不能整包覆盖项目定制。

`stack_runtime.reuse_probe(profile, report, receiver)`只读比较相关身份。实际receiver由可信宿主提供，不能信任产品自行声明权限。已知变化返回REPROBE；必要观察缺失、namespace目录未知、原生依赖未覆盖等返回UNKNOWN；完整且匹配才REUSE。仅业务输入变化不自动重跑全部环境诊断。这是对指定操作旧证据的适用性判断，不是新的调度或门禁，不等于业务输出PASS。

`stack_handoff.py deliver --materials MATERIALS --output NEW`写新的公开交付目录，布局为`capabilities/<name>/<encoded-version>/`和`delivery.json`。版本原值在清单中保留，目录安全编码。所有输出先在内存核对；私有检查代码、独立预期与本机profile不进入公开交付。宿主源码包仍可带checker，不能将整包暴露给生产者。

目标在交付目录按包guide重新discover/bind，必要时执行所选observe/probe；新venv由宿主按声明建立，不复制开发venv。后续新输入运行只依靠目标公开文件和明确宿主工具。独立检查单独交付；完整旧报告按归档路径取回，不读失效scratch或重跑业务。

## 后续技术栈作者

[author-template/capability.json](author-template/capability.json)是待填的最小清单模板，[作者说明](author-template/README.md)列出应实现文件。可运行的完整样例为各自独立分发的Qt/Python包；模板本身不是第三个已验能力。

已有通用工具和项目配置足够时直接绑定；可复用的栈专属发现/配置/诊断才做新包。新栈以独立名称/版本声明所需角色，复用材料格式和原prepare/consume/upgrade，不为每种栈增加核心分支。必要的原生库观察可复用`native_dependencies.py`；当前实现是明确入口的macOS otool观察，不能套用于未验证的其他loader。

Node/浏览器按真实包版本、浏览器与缓存做启动/页面操作；媒体按实际字体/编解码器转换小材料；服务复用既有SQLite、临时目录、端口、网络与凭据资源。只对实际选择项验证，不要求安装所有栈。不支持的组合明确待验，可用项目显式配置和范围验证继续，不自动禁止正常使用。
