# 完整源码回归的规范依赖

完整源码已携带历史 v2.8.0 规范的101个原始文件，位于
`devtools/specifications/Harness_Foundry_v2_8_Start_Package/`（364,345字节）。
它们只用于历史编译器、校验器及兼容性回归。通用运行ZIP不包含或依赖这套规范，
普通用户不需要准备 sibling，也不因此恢复已退役的 Start Package/Driver 入口。

旧 `spec_lock/HF28_SPEC_LOCK.json` 原字节保留，仍表示旧物理 sibling 的绑定。
新 `HF28_DEVELOPMENT_SPEC_LOCK.json` 明确绑定仓库内开发路径、旧锁摘要，以及同一101文件的摘要。
规范内容、2.8.0版本、validator身份与旧内容摘要
`be81e6b46573abcbff0a9851812b3b2bb78814928e57a59d65a2b5bb733b8503` 没有改变。
默认定位只读仓库内副本，不隐式搜索或借用本机 sibling；缺文件或锁不一致时报告失败。

在按[开发依赖说明](USER_GUIDE.md#仅维护-foundry-源码时需要的开发依赖)建立项目虚拟环境后，
从源码根执行：

```bash
.venv/bin/python -B devtools/verify_development_spec.py
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -p 'test_*.py' -v
```

第一条只校验已交付材料，不安装、不下载、不生成新锁；仍执行原规范只读validator，
核对文件集合/摘要和调用前后未写规范。第二条是完整源码回归，不能作为真实模型、业务目标或发布接受。
将源码复制到没有相邻规范的干净目录时，连同这份开发目录和两个锁一起复制即可；
不要复制旧 `.venv`、缓存、运行记录或报告作为依赖。

确需读取历史物理 sibling 时，可以显式调用
`tools/lock_spec.py --verify spec_lock/HF28_SPEC_LOCK.json`；其旧路径/身份约束不变。
`tools/lock_spec.py` 默认只输出当前开发绑定。它的显式写锁选项不属于正常测试准备，
不得为绕过规范差异而重锁；升级规范应单独评审并保留旧版。
