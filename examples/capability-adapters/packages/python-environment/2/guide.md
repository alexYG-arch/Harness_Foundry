# Python 环境接入 1

这个包保留指定解释器及 `.venv` 的调用语义，实际导入声明模块，记录 Python 版本、prefix、模块来源，并执行 Decimal 和 SQLite 的小计算。环境探测成功只说明这些操作可用，不能替代业务结果检查。

工具角色是 `project-python`，可以与 Qt 包的 `qt-python` 分别绑定；最终系统可执行文件相同也不把两个 venv 合并。包不安装依赖、不联网、不自动选择另一解释器、不修改父进程环境、不重试。宿主继续负责授权、预算、报告归档与接续。

## 准备和调用

`bind` 只读取明确路径及文件事实，不执行解释器。先在目标的新目录建立适用的 venv，不能从开发设备复制旧 venv。以下 `PY` 指目标明确选择的解释器，`PKG` 指交付目录中的本包，所有路径由项目实际填写：

```sh
"$PY" -I -B "$PKG/python_environment.py" bind --python "$PY" --project-path /absolute/project --output /absolute/control/python-profile.json
"$PY" -I -B "$PKG/python_environment.py" probe --profile /absolute/control/python-profile.json --input /absolute/control/probe-input.json --cwd /absolute/scratch --report-dir /absolute/reports/probe-001
"$PY" -I -B "$PKG/python_environment.py" run --profile /absolute/control/python-profile.json --cwd /absolute/project --report-dir /absolute/reports/task-001 --module-name project_package.cli -- --input /absolute/new-input.json
```

也可用 `run --script /absolute/project/tool.py`。模块及脚本的同级 import 通过 `bind --project-path` 显式加入；`-I` 不从 cwd 自动加入项目路径，`-B` 避免解释器字节码写入。保留 site-packages，不加 `-S`。项目模块仍可能自行写文件、启动子进程或访问网络，其实际允许范围由原执行宿主控制；参数不会授予权限。

公共输入示例（不是私有预期）：

```json
{"schema_version":"1","modules":["json","project_package"],"decimal_values":["0.10","0.20"],"sqlite_values":[2,3]}
```

profile 格式版本为 1，能力包版本为 1，实际 Python 版本另由探测记录。`tools.project-python` 为调用路径；`extensions.python.project_paths` 明确模块根；observations 包含解释器、可见的 `pyvenv.cfg`，并可通过重复 `--observe-module-file` 绑定有关模块文件。运行前这些已绑定文件改变时，另存新 profile 后合法接续，不覆写旧记录。

macOS 原生扩展依赖应在需要时明确观察。受限接收器可能允许读取 `_decimal`、`_sqlite3` 模块本身，却不能通过 Homebrew `opt` 别名找到其依赖库；普通终端 import 成功不能代替这种环境验证。可用已声明的 `otool` 形成参数化适配：

```sh
"$PY" -I -B "$PKG/python_environment.py" observe-native --profile /absolute/control/python-profile.json --input /absolute/control/probe-input.json --otool /usr/bin/otool --report-dir /absolute/reports/native-observation-001 --adapt-loader-paths --output /absolute/control/python-native-profile.json
```

该调用先用指定解释器查询所选模块位置，再由同源 `native_dependencies.py` 记录每次 `otool -L` 并观察有关依赖。`find_spec` 查询嵌套名称时可能导入父包，因此这也是实际命令，不能塞进纯准备或当作免费预检。已知 macOS 布局下可生成明确的库读取目录和 DYLD 路径；同名显式赋值冲突会保留诊断，不静默覆盖。新的 profile 另存，旧 profile、失败和消耗保留。它仍须通过宿主原 scope/Readback 接入，不授予新权限、不安装缺库；`native_import_verified:false` 明确表示观察并非实际 import 或业务通过。随后使用新 profile 运行实际 producer/checker probe。

观察只沿已选模块的实际加载路径记录链接，`extensions.path_aliases` 保留链接与真实目标，`read_paths` 包含必要的真实链接父目录提案。这不是权限：在本机接收器上须核对父目录元数据的可见范围，并由宿主按原 Readback 接入；不能只给真实库文件权限就宣称可重新发现环境。复用会重核已记录链接，未知状态不当作匹配。`/usr/bin/otool` 可能是需要开发工具的启动器；可显式传入宿主选定的实际工具路径，不能把工具文件存在当作启动成功。

没有完整的有关原生依赖观察时，本次实际 import 可正常通过，但未来环境证据复用保持未确认。`observe-native` 首批支持已选 macOS Mach-O 依赖；其他平台可继续使用显式项目配置和实际 probe，不因此强制调用 otool。

环境变量来自宿主允许继承的环境，再应用 profile 的显式 `environment.set` 和 `environment.prepend`；同名变量不能同时采用两种操作。Python `-I` 忽略 `PYTHONPATH` 等隐式 Python 启动变量，项目模块位置由上面的显式字段决定。profile 只保存明确的非秘密值，不导出整个宿主环境或凭据。

## 独立检查及恢复

宿主将 `check_python.py`、公开的 `python_probe.py` 和 `stack_runtime.py` 同字节复制到保护域，把 profile 及独立预期也作为检查依赖。私有 expected 不进入公开交付件。宿主需要声明解释器、标准库、venv、所选模块及输入的必要读取范围，以及新 report/scratch 写资源。

```sh
"$PY" -I -B /absolute/protected/check_python.py --profile /absolute/protected/python-profile.json --input /absolute/control/probe-input.json --expected /absolute/protected/expected.json --cwd /absolute/scratch --report-dir /absolute/reports/check-001 --report /absolute/reports/check-summary-001.json
```

检查器默认在实际检查接收器内执行保护副本的探测一次，然后比较独立预期。不会读取生产者报告冒充独立检查。`FOUNDRY_VERIFIER_ROOT` 存在时会确认脚本、公开依赖、profile 和预期都来自保护域。`FOUNDRY_REPORT_DIR` 可替代 `--report`，输出原 STRUCTURED_V1。

私有预期由项目独立维护，例如：

```json
{"schema_version":"1","python":{"prefix":"/absolute/project/.venv","require_venv":true,"version_min":[3,11]},"modules":{"project_package":{"origin_root":"/absolute/project"}},"calculation":{"decimal_sum":"0.30","sqlite_count":2,"sqlite_sum":5}}
```

模块规则支持精确 `origin`、`origin_root`、`sha256`；不能要求公共输入未声明的模块。检查完整 import、`_decimal`/`_sqlite3` 原生扩展、解释器调用和 prefix、小计算；缺依赖、未完成捕获或来源变化为 ERROR，明确预期不符为 ASSERTION。业务自身的断言由业务检查器负责，不把所有非零退出都归为环境问题。

每次实际命令必须用新 report-dir；目录已存在时在派发前停止，旧文件保留。捕获完整后，`python_environment.py read --report-dir ...` 只取回命令记录；检查器恢复用原参数加 `--recover` 并指定一个新的 summary 路径，不重复 import。`--recover` 仅接受该检查器的旧捕获，缺附件或未知完成状态保持 ERROR。宿主仍负责归档 observation.json、invocation.json、stdout.txt、stderr.txt 和 summary；恢复不是新的执行预算。

`--receiver /absolute/receiver.json` 可附宿主声明的实际接收器及权限条件供复用比较。缺少此材料时不自动认定旧探测可复用。成功报告的 observations 包含真实加载模块文件：同路径模块原地改变会触发有关操作的复验，只有新业务输入变化不要求重复全部环境探测。namespace package 可实际导入，但没有具体源文件的目录内容不在文件观察范围，相关复用保持未确认，不因此把本次实际导入判失败。观察不覆盖未声明插件、外部服务状态或整棵 site-packages。

## 目标交付和边界

公开交付包含本工具及 `runtime_files`，保留相邻文件布局；不交付 checker 或私有 expected，不复制开发 profile 的绝对路径。在目标目录重新运行 `bind`，按新输入运行工具和所需独立检查。仍依赖显式声明的宿主 Python/venv，不回读 Foundry 开发 runs 或本次测试目录。

首批探测是 CPython、venv、模块 import 和标准库原生扩展。第三方二进制扩展、GPU、其他平台及具体业务需要各自实际所选用例，不把这里的小计算通过扩大为全部环境或产品验收。授权工程测试与正式目标 Harness 验收分开记录，不消耗或重置 WP10 的预算。
