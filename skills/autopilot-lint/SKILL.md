---
name: autopilot-lint
description: AutoPilot 项目代码自检与通用 lint 修复规范。每完成一个阶段/批量关键字或功能开发后、在向用户报告"完成"之前调用，自动消除项目里反复出现的 PyCharm/lint 告警并跑测试套，只把无法自动判定的独立问题留给用户。适用于 D:/projectx/AutoPilot。
---

# AutoPilot 代码自检规范

每完成一段开发（尤其是新增关键字、新增 UI 组件、新增模块）后，**在报告完成前**执行本自检，自动修掉通用告警，避免让用户逐文件反馈。

## 一键自检/自修

在项目根 `D:/projectx/AutoPilot` 下运行：

```
.venv/Scripts/python.exe skills/autopilot-lint/autocheck.py
```

它会：① 自动修掉确定性强的通用告警（XML 折叠、ctx→_ctx、broad-except，**覆盖 autopilot/ 与 tests/**）；
② **硬失败**报告未使用 import（AST 检测，覆盖 autopilot/ 与 tests/，尊重 `# noqa`/`# noinspection` 与 `TYPE_CHECKING`）；
③ **硬失败** ANDROID_ONLY 元数据一致性、iOS parity 骨架离线校验；
④ 报告需人工判断的项；⑤ 跑全部测试套（显式列表 + `tests/test_*.py` 自动发现；离屏 PyQt UI 套见 `TEST_SUITE_EXCLUDE` 默认跳过）。
脚本幂等，可反复运行；退出码非 0 即存在未用导入或测试失败。改完后据清单手工补 noinspection，再复跑。

**日常（Agent/批量 UI 改动）**：先跑静态检查，不拖全量测试进度：

```
.venv/bin/python skills/autopilot-lint/autocheck.py --no-test
```

## 通用告警 → 标准修法（背景知识）

> 核心约束：**关键字函数被引擎以 `func(ctx, **kwargs)` 调用，kwargs 的 key = 参数 id**。
> 因此关键字函数的形参名必须等于关键字参数 id —— camelCase 的不能改名，只能加 noinspection。

| 告警                              | 原因                                                                      | 标准修法                                                                                           |
|---------------------------------|-------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| 未使用形参 `ctx`                     | 关键字必传首参但函数体没用到                                                          | **改名 `ctx`→`_ctx`**（位置传参不受影响；比注解可靠）。脚本自动做                                                      |
| 实参名称应小写                         | camelCase 的关键字参数 id（如 isScroll/outVar/tableName）                        | 函数 `@keyword` **上一行**加 `# noinspection PyPep8Naming`（不能改名）                                     |
| 隐藏内置名称                          | 参数名是 type/id/format/input/str 等                                         | 加 `# noinspection PyShadowingBuiltins`（多个合并：`PyPep8Naming,PyShadowingBuiltins`）                |
| 从外部作用域隐藏名称                      | 参数名 shadow 了 import（如 `keyword`/`time`）或内层函数变量                          | 加 `PyShadowingNames`；内层函数局部变量可直接改名                                                             |
| 异常子句过于宽泛                        | `except Exception:`（容错/忽略式，有意）                                          | try 上一行加 `# noinspection PyBroadException`。脚本自动做                                               |
| 'object' 未解析特性引用 / 期望 WebDriver | `BrowserManager/AppiumManager` 的 `driver()/open()/create()` 返回 `object` | 这些方法返回类型标 **`Any`**（`from typing import Any`），一处消一大片                                           |
| 未解析的引用（第三方库）                    | 可选依赖懒导入（selenium/appium/redis/kafka/cv2/lxml/yaml…）                     | import 上一行 `# noinspection PyUnresolvedReferences`                                             |
| 访问受保护成员 `_xxx`                  | 如 lxml `etree._Element`、`mgr._driver`、SQLAlchemy `row._mapping`         | 访问处上一行 `# noinspection PyProtectedMember`；类型注解可字符串化                                            |
| 无效的类型实参                         | `list[X]` 的 X 是 `A                                                      | B                                                                                              | C` 运行期 UnionType | 用 `typing.Union[...]` 定义类型别名 |
| 无法实例化抽象类 'Element'              | `etree.Element(tag)`（lxml 工厂被误判抽象）                                      | 改用 `parent.makeelement(tag, {})`                                                               |
| 未使用 import / 局部变量               | 残留导入、死赋值（如 `pkg = None` 后被覆盖）                                           | 直接删除。**有意保留**的副作用导入（关键字注册）/懒加载校验/依赖探测：行尾加 `# noqa: F401`（autocheck 会尊重并不再报）                    |
| 类型 int/float/str 不匹配            | 如 `move_by_offset(dx/steps)` 传 float                                    | 显式 `int(...)`；或修正注解                                                                            |
| 拼写错误（领域词）                       | appium/adb/jsonpath/udid/stepset…                                       | 加到 `.idea/dictionaries/<用户名>.xml`（如 Administrator.xml），`dictionary name` 必须=用户名，否则 PyCharm 不加载 |
| XML 标签具有空体                      | 资源 XML 里 `<x></x>`                                                      | 折叠为 `<x/>`（lxml 等价）。脚本自动做                                                                      |

## 测试桩（tests/ 假驱动）的标准抑制

测试替身（Fake/桩类）的方法多按"接口形状"写，PyCharm 会报*方法可 static*、*未用形参*、
*别名大写*、*可选包未列依赖*、*protected 访问*等——这些是既定写法，不改逻辑，统一就近抑制：

| 场景                                    | 标准修法                                                           |
|---------------------------------------|----------------------------------------------------------------|
| Fake/桩类方法"可为 static" + 形参未用           | **类定义上一行**加 `# noinspection PyMethodMayBeStatic,PyUnusedLocal` |
| 别名导入大写（`import tree as T`）            | import 上一行 `# noinspection PyPep8Naming`                       |
| 可选包导入（`import cv2`/numpy 等不在 base 依赖） | import 上一行 `# noinspection PyPackageRequirements`              |
| 测试里访问产品类的 `_xxx`（白盒断言）                | 访问处或函数上一行 `# noinspection PyProtectedMember`                   |
| HTTP handler 的 `do_GET/do_POST`       | 类上一行 `# noinspection PyPep8Naming`（协议固定大小写）                    |
| `bytes(QByteArray)`、桩对象传强类型形参         | 调用处上一行 `# noinspection PyTypeChecker`                          |

> noinspection 注释**必须紧贴**目标行（中间不能有空行，否则不生效）。

## 不要去改（误报/低价值）

- **PyQt 信号 `pyqtSignal` 找不到 `emit`/`connect`**：PyCharm 对 PyQt 信号的已知误报，代码正确。自定义 `pyqtSignal` 行上的 `.emit`/`.connect` 可由 autocheck 自动补 `# noinspection PyUnresolvedReferences`；`QAction.toggled/triggered.connect` 需手写抑制。
- **`QApplication.instance()` 找不到 `style`/`styleHints`/`setPalette`**：对返回值 `cast(QApplication, QApplication.instance())` 即可。

## PyCharm 消警归类（已沉淀，2026-07）

Windows 宿主验证与 UI/检视器迭代中批量处理过的问题，按类别归档如下（agent 改代码时优先对照，避免重复踩坑）。

### A. 真代码 / 类型（必须改逻辑）

| 现象                                      | 标准修法                                                           |
|-----------------------------------------|----------------------------------------------------------------|
| `wait(timeout=float)` 类型不匹配             | `int(max(0, …))`                                               |
| 循环内变量「可能未赋值」                            | 循环前初始化（`ready=[]`、`stdout=b""`）                                |
| `ast.walk(expr)` / `.value` 类型告警        | `cast(ast.AST, …)`；`isinstance(n, ast.Constant)` 后再读 `.value`  |
| `TYPE_CHECKING` 导入报未使用                  | 注解写 `Locator \| None`（配合 `from __future__ import annotations`） |
| 函数内 import 遮蔽模块级同名                      | 删除内层重复 import，用模块级符号                                           |
| 未使用形参 / 占位参数                            | 前缀 `_`（`_backend`、`_platform`）                                 |
| `steps=[]` 后立刻 append 首项                | 改为 `[Step(...)]` 字面量初始化                                        |
| tools 访问 `_load_case`、`_swipe_by_ratio` | 改 `load_case` / `getattr(session, "_swipe_by_ratio")`          |

### B. PyQt / chrome 边界（误报或架构）

| 现象                                            | 标准修法                                                                 |
|-----------------------------------------------|----------------------------------------------------------------------|
| `pyqtSignal.connect` / `emit` 未解析             | `# noinspection PyUnresolvedReferences`（autocheck 可自动补 signal 行）     |
| chrome 访问 `MainWindow._fill_recent_menu` 等    | `getattr(host, "_name")` 或 `MenuBarChrome._host_slot(host, "_name")` |
| 子面板访问 `_ph`、`_refresh_tree_icons`             | 组件公开方法：`apply_placeholder_theme`、`apply_tree_theme`                  |
| `_params_target() -> object` 导致 `.params` 未解析 | 返回 `Step \| StepVerbs \| None`                                       |
| 侧栏直接访问子组件内部控件                                 | 走组件公开方法（如 `focus_query`）                                             |

### C. UI 主题（`check_ui_theme.py` 硬失败）

| 现象                                 | 标准修法                                                 |
|------------------------------------|------------------------------------------------------|
| `_ui_theme = "light"` 写死           | `__init__` 用 `""` 占位，`apply_theme` 内 `resolve_theme` |
| 检视器 QSS 缺 `QTableWidget::item`     | 补选择器（勿用 `background:#fff` 盖住斑马纹）                     |
| `check_ui_theme.py` 内 regex/AST 告警 | `re.escape`、去掉多余 `\}`；内嵌函数参数勿遮蔽外层 `text`             |

### D. 设备容错（`check_device_readiness.py` 硬失败）

检视/镜像/运行入口须走 `device_readiness` 模块，禁止 Mixin 内手写 `_devices[0]`、散落平台分支。

### E. 测试环境（备忘，非 autocheck 自动修）

| 场景                   | 做法                                        |
|----------------------|-------------------------------------------|
| Windows 无控制台跑 pytest | `pytest -p no:xonsh`（pymobiledevice3 依赖链） |
| UI 批量改动后快速门禁         | `autocheck.py --no-test`                  |
| 全量 60+ 套测试耗时长        | 静态先绿，再按需跑相关 `tests/test_*.py`             |

### F. 产品行为（非 lint，但同期修复）

| 问题                 | 处理                                                       |
|--------------------|----------------------------------------------------------|
| 窗口标题               | 固定 `AutoPilot`（工程名不进标题栏）                                 |
| 镜像停止后状态栏仍显示「实时操作中」 | `MirrorPanel._stop()` 调 `_sync_idle_label(stopped=True)` |
| 检视器拉宽后底纹露白         | 列宽 `max(内容宽, viewport宽)` + splitter resize 同步            |

## 收尾纪律

1. 自动修复后必须 `py_compile` 全过 + import 成功（脚本含）。
2. 关键字注册总数应保持不变（当前基线见项目记忆/ROADMAP），覆盖率不回退。
3. 全部测试套必须全绿（`discover_test_suites()` 显式 + 自动发现，当前约 53 个，脚本含）。任何因清理导致的失败都要回滚或修正，绝不带病报告完成。
4. 真 bug（清理中偶尔发现，如声明却没真正使用的参数、引用未赋值属性）要单独指出并修，不要静默吞掉。
