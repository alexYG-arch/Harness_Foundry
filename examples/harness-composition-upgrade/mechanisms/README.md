# 两个机制样例：固定输入与准备状态

这些文件是 S1/S2 的源码测试样例，没有执行模型组装、批准 Build、创建真实 Program 或取得控制器接受。`versions/` 保存真实 G/N 字节；`custom/current/` 是合成用户当前文件 C；`expected/` 是预先写定的语义参考候选，**不是已接受 A**。只有以后真实接受应用后，外层才能从 `read-build` 得到接受身份并另写 lineage，关联实际 A/G；这里不填虚构身份。

- [DOC](doc/README.md)：保留用户标题、顺序和备注，升级引用显示及优先级，随后无 G 的项目增量修改。
- [API](api/README.md)：timeout 默认 10→15→30，用户20保留两次；旧响应合同及新增 health 字段。

`inputs.json` 中 C/G/N 的 `file` 相对于该 manifest，`executable` 是执行位；`missing:true` 表示不存在；`G:null` 表示没有可靠旧组件，须按项目增量修改处理。确定性 helper 只处理可由字节和执行位证明的情况；`expected/` 里的语义整合不得冒充 helper 自动合并结果。

`apply.json` 固定候选与旧状态，每项 `path` 相对临时目标，`expected`/`desired` 相对 manifest。先检查候选，再以真实应用授权执行；helper 输出不等于独立验收。这里的单文件更新示例与 S2 helper 的删除、改名、共享文件测试互补，不另加控制器规则。

源码测试只在临时目录复制样例；不会写入样例本身、真实项目或控制库。固定参考内容与独立检查器分开存放，但本仓库中的位置本身不提供运行隔离：S3/S4 须将实际检查器及其 expectation 依赖纳入受保护副本，并确认实际读取该副本。两组不会替代三组业务验收。
