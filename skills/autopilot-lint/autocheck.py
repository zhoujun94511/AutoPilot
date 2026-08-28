"""AutoPilot 代码自检/自修脚本（幂等）。

用途：每完成一个阶段/批量代码后运行，自动消除项目里反复出现的通用 lint 告警，
并报告需要人工判断的项，最后跑测试套。

用法（在项目根下，cwd 任意均可）：
    .venv/bin/python skills/autopilot-lint/autocheck.py          # macOS/Linux
    .venv/Scripts/python.exe skills/autopilot-lint/autocheck.py  # Windows

自动修复（安全、确定性强）：
  1) 资源 XML 空标签 <x></x> → <x/>（lxml 语义等价）
  2) @keyword 函数体未用 ctx → 首参 ctx 改名 _ctx（引擎按位置传参，不影响派发）
  3) bare `except Exception:` / `except:` 对应 try 上方加 `# noinspection PyBroadException`
     —— 覆盖 autopilot/ 与 tests/（测试目录只做 broad-except，不动 ctx）
  4) 自定义 pyqtSignal 的 `.emit(` / `.connect(` 上一行补 `# noinspection PyUnresolvedReferences`
     —— PyCharm 解析不出动态生成的 signal；QAction.toggled/triggered.connect 同理手写抑制
广度检查（ruff，venv 内；配置见根 ruff.toml）：
  - 跑 `ruff check autopilot tests`，拿 pyflakes(F)+E9/E4/E7 这批与 PyCharm 重叠最大的“真错”面
    （未用/未定义名、重定义、f-string 误用、比较 None/True、跨版本语法如 f-string 内反斜杠…）。
  - 本机无 PyCharm，无法跑其 headless inspect；ruff 作为主动、毫秒级的替代广度面，
    PyCharm 特有项（相对导入层级、signal.emit 误报、作用域遮蔽）由下面的定向检查补齐。
  - ruff 未安装则跳过（不失败）；装：`.venv/Scripts/python.exe -m pip install ruff`。
硬失败（必须清理，否则退出码非 0）：
  - 未使用的 import（AST 检测，覆盖 autopilot/ 与 tests/；排除 __init__.py 再导出与 __all__；
    尊重 `if TYPE_CHECKING:` 与前向引用字符串注解）
  - 相对导入无法解析（点数算错层级 / 越过顶层包）—— 这类只在运行到该分支才崩，测试常漏，必须静态拦下
  - UI 主题一致性（`check_ui_theme.py`：QSS 键名、禁止 palette()、apply_theme/init_panel_style、语义色）
  - 设备判空/容错集中化（`check_device_readiness.py`：禁止 Mixin 手写平台分支、须走 device_readiness）
  - ruff 报出的真错（基线已清零，再出即硬失败）
  - ANDROID_ONLY_KEYWORD_IDS 与 mobile.xml platforms="android" 不一致
  - ios_parity_skeleton 结构校验失败
仅报告（需人工判断，不自动改）：
  - @keyword 函数有 camelCase 参数 id 但缺 `# noinspection PyPep8Naming`
  - shadow 内置(type/id/format/input/str/list…)的参数缺 PyShadowingBuiltins
  - 嵌套函数局部名遮蔽外层作用域同名（PyShadowingNames，循环变量等）
  - 拼写词疑似缺失（领域词应加到 .idea/dictionaries/*.xml）

注：PyCharm 专有检查（方法可为 static、protected 访问、别名大写、可选包 import）
为测试替身/桥接代码的既定写法，统一用就近 `# noinspection ...` 抑制（见 tests/ 假驱动类）。

PyCharm 消警归类（已沉淀，2026-07 Windows 宿主验证 + UI/检视器迭代）：
  A) 真代码/类型（必须改逻辑，autocheck/ruff 可拦）
     - subprocess.wait(timeout=…) 须 int，勿传裸 float
     - 循环/try 内局部变量「可能未赋值」→ 进入循环前初始化（如 ready=[], stdout=b""）
     - ast.walk / 注解：expr 先 cast(ast.AST, …) 或 isinstance(..., ast.Constant) 再读 .value
     - TYPE_CHECKING 导入：注解用 Locator | None（非引号串），避免「未使用 import」误报
     - 函数内重复 import 遮蔽模块级同名（如 ios_driver_backend）→ 删内层 import
     - 未使用形参 → 前缀 _（_backend/_platform/_img_h）或删多余赋值（plat = ""）
     - 多步 list 初始化 → 列表字面量（[a, b] + append 循环除外）
     - tools/ 脚本访问 _load_case、_swipe_by_ratio → 改公开 API 或 getattr(module, "_x")
  B) PyQt / PyCharm 误报（代码正确，抑制或 cast）
     - QApplication.instance() 的 style/styleHints/setPalette → cast(QApplication, instance())
     - pyqtSignal / QAction 的 .emit / .connect → # noinspection PyUnresolvedReferences（脚本可补）
     - chrome 层访问 MainWindow._xxx → getattr(host, "_slot") 或 MenuBarChrome._host_slot()
     - 子组件访问 _ph、_refresh_tree_* → 父类公开方法（apply_placeholder_theme、apply_tree_theme）
     - ParamForm._params_target 返回 Step|StepVerbs|None，避免 object.params 未解析
  C) UI 主题静态审计（check_ui_theme.py 硬失败）
     - 勿写死 _ui_theme = "light"|"dark"；__init__ 可 _ui_theme = ""，apply_theme 再 resolve
     - Dock 内面板 QSS 须含 QTableWidget::item、QHeaderView::section 等 chrome 选择器
     - init_panel_style / apply_theme / semantic_color 约定见 check_ui_theme.py 规则表
  D) 设备容错（check_device_readiness.py 硬失败）
     - 检视/镜像/运行入口须走 device_readiness，禁止 Mixin 内手写 _devices[0] 分支
  E) 测试环境（文档化，非 autocheck 默认修复）
     - Windows 无控制台 pytest：pymobiledevice3→xonsh 插件冲突，用 pytest -p no:xonsh
     - 全量测试耗时长：autocheck.py --no-test 做静态门禁后再按需跑套
  详见 skills/autopilot-lint/SKILL.md「PyCharm 消警归类」一节。
"""

from __future__ import annotations

import argparse
import ast
import glob
import os
import re
import subprocess
import sys
from typing import cast

# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def _find_project_root() -> str:
    """定位仓库根（含 autopilot/ 与 tests/），不依赖 IDE 的 cwd。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.dirname(os.path.dirname(here)),  # skills/autopilot-lint → 项目根
        os.getcwd(),
    ]
    for root in candidates:
        if os.path.isdir(os.path.join(root, "autopilot")) and os.path.isdir(
                os.path.join(root, "tests")):
            return root
    return os.getcwd()


def _venv_python(root: str) -> str:
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return p
    return sys.executable


ROOT = _find_project_root()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
KW_GLOB = os.path.join(ROOT, "autopilot", "keywords", "**", "*.py")
SRC_GLOB = os.path.join(ROOT, "autopilot", "**", "*.py")
TEST_GLOB = os.path.join(ROOT, "tests", "*.py")
XML_GLOB = os.path.join(ROOT, "autopilot", "metadata", "keyword_defs", "*.xml")
PY_BUILTINS = {"type", "id", "format", "input", "str", "list", "dict", "set",
               "bytes", "filter", "map", "object", "len", "min", "max"}


# ---------------------------------------------------------------- auto-fixes
def fix_xml_empty_tags() -> int:
    n = 0
    for p in glob.glob(XML_GLOB):
        s = open(p, encoding="utf-8").read()
        new = s
        for _ in range(3):  # 处理嵌套空标签
            new = re.sub(r"<(\w+)>\s*</\1>", r"<\1/>", new)
        if new != s:
            open(p, "w", encoding="utf-8").write(new)
            n += 1
    return n


def _uses_ctx(fn: ast.FunctionDef) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "ctx" for n in ast.walk(fn))


def _is_keyword_fn(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef) and any(
        isinstance(d, ast.Call) and getattr(d.func, "id", "") == "keyword"
        for d in node.decorator_list)


def _insert_broad_except_noinspection(lines: list[str]) -> list[str]:
    """在每个 `except Exception:` 对应的 `try:` 上方补 `# noinspection PyBroadException`。"""
    ins = set()
    for idx, ln in enumerate(lines):
        if re.match(r"^\s*except (Exception)?:\s*(#.*)?$", ln):
            ind = len(ln) - len(ln.lstrip())
            for j in range(idx - 1, -1, -1):
                lj = lines[j]
                if not lj.strip():
                    continue
                jd = len(lj) - len(lj.lstrip())
                if jd == ind and lj.strip() == "try:":
                    if j > 0 and "noinspection" in lines[j - 1]:
                        break
                    ins.add(j)
                    break
                if jd < ind:
                    break
    if not ins:
        return lines
    res = []
    for idx, ln in enumerate(lines):
        if idx in ins:
            res.append(" " * (len(ln) - len(ln.lstrip())) + "# noinspection PyBroadException")
        res.append(ln)
    return res


def fix_unused_ctx_and_except() -> int:
    changed_files = 0
    # 源码：ctx→_ctx + broad-except；测试目录：仅 broad-except（ctx 改名不适用于测试）
    for p in glob.glob(SRC_GLOB, recursive=True) + glob.glob(TEST_GLOB):
        is_src = p.replace("\\", "/").startswith("autopilot/")
        s = open(p, encoding="utf-8").read()
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        lines = s.split("\n")
        if is_src:
            # ctx → _ctx（首参叫 ctx 但函数体未用到；含 @keyword 与普通辅助函数）
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    a = node.args.args
                    if a and a[0].arg == "ctx" and not _uses_ctx(node):
                        i = node.lineno - 1
                        if "(ctx:" in lines[i] or "(ctx," in lines[i] or "(ctx)" in lines[i]:
                            lines[i] = (lines[i].replace("(ctx:", "(_ctx:", 1)
                                        .replace("(ctx,", "(_ctx,", 1)
                                        .replace("(ctx)", "(_ctx)", 1))
        lines = _insert_broad_except_noinspection(lines)
        new = "\n".join(lines)
        if new != s:
            open(p, "w", encoding="utf-8").write(new)
            changed_files += 1
    return changed_files


def _prev_nonblank(lines: list[str], i: int) -> int:
    j = i - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    return j


def fix_signal_emit_noinspection() -> int:
    """给「自定义 pyqtSignal 的 .emit( / .connect(」就近补 noinspection（PyCharm 解析不出动态 signal）。"""
    changed = 0
    for p in glob.glob(SRC_GLOB, recursive=True):
        s = open(p, encoding="utf-8").read()
        names = set(re.findall(r"^\s*(\w+)\s*=\s*pyqtSignal\(", s, re.M))
        if not names:
            continue
        sig_call = re.compile(r"\.(\w+)\.(?:emit|connect)\(")
        lines = s.split("\n")
        ins = set()
        for i, ln in enumerate(lines):
            hit = any(m.group(1) in names for m in sig_call.finditer(ln))
            if not hit or "noinspection" in ln:
                continue
            j = _prev_nonblank(lines, i)
            if j >= 0 and "noinspection" in lines[j]:
                continue
            ins.add(i)
        if not ins:
            continue
        res = []
        for i, ln in enumerate(lines):
            if i in ins:
                indent = ln[: len(ln) - len(ln.lstrip())]
                res.append(indent + "# noinspection PyUnresolvedReferences")
            res.append(ln)
        open(p, "w", encoding="utf-8").write("\n".join(res))
        changed += 1
    return changed


# ---------------------------------------------------------------- reports
def report_bad_relative_imports() -> list[str]:
    """静态解析每条相对导入：按文件所在包算出目标路径，磁盘上不存在则报（点数/层级错）。"""
    out = []
    for p in glob.glob(SRC_GLOB, recursive=True) + glob.glob(TEST_GLOB):
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        pkg = rel.split("/")[:-1]                 # 文件所在目录即其包路径
        s = open(p, encoding="utf-8").read()
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not (isinstance(n, ast.ImportFrom) and n.level):
                continue
            cut = len(pkg) - (n.level - 1)        # level=1 当前包，每多一点上移一层
            dots = "." * n.level + (n.module or "")
            if cut < 0:
                out.append(f"  {rel}:{n.lineno} 相对导入越过顶层包: {dots}")
                continue
            mod = n.module.split(".") if n.module else []
            target = os.path.join(ROOT, *pkg[:cut], *mod)
            if not (os.path.isdir(target) or os.path.isfile(target + ".py")):
                out.append(f"  {rel}:{n.lineno} 相对导入无法解析: {dots}（应指向 "
                           f"{os.path.relpath(target, ROOT)}）")
    return out


def report_duplicate_keyword_ids() -> list[str]:
    """同一 keyword id 在 keyword_defs/*.xml 里出现多次——by_id 后到覆盖会让前面的定义
    变死数据、且关键字库可能重复显示。每个 id 应只定义一次。"""
    out = []
    for p in glob.glob(XML_GLOB):
        ids = re.findall(r"<keyword id=['\"]([^'\"]+)['\"]", open(p, encoding="utf-8").read())
        seen, dup = set(), set()
        for i in ids:
            (dup if i in seen else seen).add(i)
        for i in sorted(dup):
            out.append(f"  {os.path.relpath(p)}: 重复 keyword id '{i}'（{ids.count(i)} 次）")
    return out


def _scope_binds(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    """函数体内（不含嵌套函数/lambda）由 for 目标 / 赋值绑定的名字 → 首次行号。"""
    binds: dict = {}

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue                          # 嵌套作用域单独处理
            if isinstance(child, ast.For):
                for t in ast.walk(cast(ast.AST, child.target)):
                    if isinstance(t, ast.Name):
                        binds.setdefault(t.id, t.lineno)
            elif isinstance(child, ast.Assign):
                for tgt in child.targets:
                    for t in ast.walk(cast(ast.AST, tgt)):
                        if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                            binds.setdefault(t.id, t.lineno)
            visit(child)

    visit(fn)
    return binds


def report_shadowing() -> list[str]:
    """嵌套函数里 for/赋值的局部名遮蔽外层函数同名（PyCharm「从外部作用域隐藏名称」）。"""
    out = []
    for p in glob.glob(SRC_GLOB, recursive=True) + glob.glob(TEST_GLOB):
        rel = os.path.relpath(p)
        s = open(p, encoding="utf-8").read()
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        lines = s.split("\n")

        def walk(node: ast.AST, ancestors: set) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    binds = _scope_binds(child)
                    for name, ln in binds.items():
                        above = lines[ln - 2] if ln >= 2 else ""
                        if name in ancestors and "PyShadowingNames" not in above:
                            out.append(f"  {rel}:{ln} 局部名 '{name}' 遮蔽外层作用域同名")
                    walk(cast(ast.AST, child), ancestors | set(binds))
                else:
                    walk(child, ancestors)

        walk(tree, set())
    return out


def report_missing_noinspection() -> list[str]:
    """报告 @keyword 函数有 camelCase / 内置同名参数但缺对应 noinspection。"""
    out = []
    for p in glob.glob(KW_GLOB, recursive=True):
        s = open(p, encoding="utf-8").read()
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        lines = s.split("\n")
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):  # 先收窄类型，再判 @keyword
                continue
            fn = cast(ast.FunctionDef, node)
            if not _is_keyword_fn(fn):
                continue
            params = [a.arg for a in fn.args.args[1:]]  # 跳过 ctx/_ctx
            camel = [x for x in params if any(c.isupper() for c in x)]
            shadow = [x for x in params if x in PY_BUILTINS]
            if not camel and not shadow:
                continue
            deco = min(d.lineno for d in fn.decorator_list)
            above = lines[deco - 2] if deco >= 2 else ""
            need = []
            if camel and "PyPep8Naming" not in above:
                need.append(f"PyPep8Naming(参数 {camel})")
            if shadow and "PyShadowingBuiltins" not in above:
                need.append(f"PyShadowingBuiltins(参数 {shadow})")
            if need:
                out.append(f"  {os.path.relpath(p)}:{fn.lineno} {fn.name} → 缺 {', '.join(need)}")
    return out


def _type_checking_import_names(tree: ast.AST) -> set[str]:
    """`if TYPE_CHECKING:` 块内的导入名视为已用（仅类型注解/前向引用）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"):
            continue
        for child in node.body:
            if isinstance(child, ast.ImportFrom):
                for a in child.names:
                    if a.name != "*":
                        names.add(a.asname or a.name)
            elif isinstance(child, ast.Import):
                for a in child.names:
                    names.add(a.asname or a.name.split(".")[0])
    return names


def _quoted_annotation_names(tree: ast.AST) -> set[str]:
    """收集字符串前向引用注解中的标识符（如 ctx: \"ExecutionContext\"）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        ann = getattr(node, "annotation", None)
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            # 简单提取合法标识符片段
            for part in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", ann.value):
                names.add(part)
    return names


def _imported_names(tree: ast.AST, lines: list[str]):
    """收集模块顶层 import 绑定名 → (binding, lineno)。

    跳过 __future__ / `import *`，以及显式标注了 `# noqa`/`# noinspection` 的 import
    —— 那是有意保留的副作用导入（关键字注册）或懒加载/依赖探测，不应报未使用。
    """
    out = []

    def _suppressed(stmt) -> bool:
        lo = stmt.lineno - 1
        hi = (getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno) - 1
        return any("noqa" in lines[i] or "noinspection" in lines[i]
                   for i in range(lo, min(hi + 1, len(lines))))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if _suppressed(node):
                continue
            for a in node.names:
                out.append((a.asname or a.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__" or _suppressed(node):
                continue
            for a in node.names:
                if a.name == "*":
                    continue
                out.append((a.asname or a.name, node.lineno))
    return out


def report_unused_imports() -> list[str]:
    """报告未使用的 import（AST，确定性强）。排除 __init__.py（多为再导出）与 __all__ 名单。"""
    out = []
    for p in glob.glob(SRC_GLOB, recursive=True) + glob.glob(TEST_GLOB):
        if os.path.basename(p) == "__init__.py":
            continue
        s = open(p, encoding="utf-8").read()
        try:
            tree = ast.parse(s)
        except SyntaxError:
            continue
        # 模块内被引用的名字（Name 读取 + 属性根 + 装饰器/注解里出现的标识符）
        used = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                used.add(n.id)
            elif isinstance(n, ast.Attribute):
                v = n
                while isinstance(v, ast.Attribute):
                    v = v.value
                if isinstance(v, ast.Name):
                    used.add(v.id)
        # __all__ 中以字符串再导出的名字
        for n in ast.walk(tree):
            if (isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets)):
                for e in ast.walk(cast(ast.AST, n.value)):
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        used.add(e.value)
        used |= _type_checking_import_names(tree)
        used |= _quoted_annotation_names(tree)
        for name, ln in _imported_names(tree, s.split("\n")):
            base = name.split(".")[0]
            if base not in used and name not in used:
                out.append(f"  {os.path.relpath(p)}:{ln} 未使用 import '{name}'")
    return out


# ---------------------------------------------------------------- ruff（广度）
def run_ruff() -> tuple[bool, list[str]]:
    """跑 ruff（venv 内）拿广度覆盖：未用/未定义名、重定义、f-string 误用、跨版本语法等。

    返回 (是否可用, 告警行列表)。ruff 未安装则视为不可用（跳过，不失败）——
    配置见项目根 ruff.toml（锁 py310、聚焦真错、排除 vendored 目录）。
    """
    py = _venv_python(ROOT)
    try:
        r = subprocess.run([py, "-m", "ruff", "check", "autopilot", "tests",
                            "--output-format", "concise"],
                           capture_output=True, text=True, encoding="utf-8",
                           cwd=ROOT)
    except OSError:
        return False, []
    if "No module named ruff" in (r.stderr or ""):
        return False, []
    out = []
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if s and not s.startswith("All checks") and not s.startswith("Found ") \
                and "fixable with" not in s and "\x1b" not in s[:5]:
            out.append("  " + s)
    return True, out


# ---------------------------------------------------------------- 移动端边界 / parity（离线硬检查）
def report_android_only_platform_mismatch() -> list[str]:
    """ANDROID_ONLY_KEYWORD_IDS 必须与 mobile.xml platforms=\"android\" 一致。"""
    out = []
    # noinspection PyBroadException
    try:
        from autopilot.metadata import load_catalog
        from autopilot.metadata.keyword_platforms import ANDROID_ONLY_KEYWORD_IDS
    except Exception as e:
        return [f"  无法加载关键字目录: {e}"]
    cat = load_catalog()
    for kid in sorted(ANDROID_ONLY_KEYWORD_IDS):
        meta = cat.get(kid)
        if meta is None:
            out.append(f"  ANDROID_ONLY_KEYWORD_IDS 含未注册关键字: {kid}")
        elif meta.platforms != ["android"]:
            out.append(
                f"  {kid}: ANDROID_ONLY 集合与 XML platforms={meta.platforms!r} 不一致"
            )
    return out


def report_ios_only_platform_mismatch() -> list[str]:
    """IOS_ONLY_KEYWORD_IDS 必须与 mobile.xml platforms=\"ios\" 一致。"""
    out = []
    # noinspection PyBroadException
    try:
        from autopilot.metadata import load_catalog
        from autopilot.metadata.keyword_platforms import IOS_ONLY_KEYWORD_IDS
    except Exception as e:
        return [f"  无法加载关键字目录: {e}"]
    cat = load_catalog()
    for kid in sorted(IOS_ONLY_KEYWORD_IDS):
        meta = cat.get(kid)
        if meta is None:
            out.append(f"  IOS_ONLY_KEYWORD_IDS 含未注册关键字: {kid}")
        elif meta.platforms != ["ios"]:
            out.append(
                f"  {kid}: IOS_ONLY 集合与 XML platforms={meta.platforms!r} 不一致"
            )
    return out


def report_parity_diff_tool_invalid() -> list[str]:
    """ios_parity_diff --validate-only 离线自检。"""
    out: list[str] = []
    script = os.path.join(ROOT, "tools", "ios_parity_diff.py")
    if not os.path.isfile(script):
        return ["  tools/ios_parity_diff.py 不存在"]
    # noinspection PyBroadException
    try:
        r = subprocess.run(
            [_venv_python(ROOT), script, "--validate-only"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env=dict(os.environ, PYTHONPATH=ROOT),
        )
    except Exception as e:
        return [f"  无法运行 ios_parity_diff: {e}"]
    if r.returncode != 0:
        out.append(f"  ios_parity_diff --validate-only 退出码 {r.returncode}")
        tail = (r.stdout + r.stderr).strip()[-400:]
        if tail:
            out.append(f"  {tail}")
    return out


def report_parity_skeleton_invalid() -> list[str]:
    """iOS parity 骨架结构离线校验（WDA/Appium 对照集）。"""
    out = []
    # noinspection PyBroadException
    try:
        from tests.ios_parity_skeleton import PARITY_CASES, validate_parity_skeleton
    except Exception as e:
        return [f"  无法导入 ios_parity_skeleton: {e}"]
    if not validate_parity_skeleton():
        out.append("  validate_parity_skeleton() 返回 False")
    for case in PARITY_CASES:
        if case.get("platform") != "ios":
            out.append(f"  parity 用例 {case.get('name')!r} platform 非 ios")
    return out


# 离屏 PyQt UI 套：按需手工跑，全量 autocheck 默认跳过（拖慢进度）
TEST_SUITE_EXCLUDE = frozenset({
    "test_chrome_components",
    "test_ui_theme",
    "test_ui_phase4",
    "test_device_status_chip",
    "test_grip_splitter",
    "test_auxiliary_region",
})


def discover_test_suites() -> list[str]:
    """合并显式列表与 tests/test_*.py 自动发现（新增测试勿漏跑）。"""
    explicit = list(TEST_SUITES)
    known = set(explicit)
    for p in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
        name = os.path.splitext(os.path.basename(p))[0]
        if name in known or name in TEST_SUITE_EXCLUDE:
            continue
        explicit.append(name)
        known.add(name)
    smoke = os.path.join(ROOT, "tests", "smoke.py")
    if os.path.isfile(smoke) and "smoke" not in known:
        explicit.insert(0, "smoke")
    return explicit


# ---------------------------------------------------------------- tests
TEST_SUITES = ["smoke", "test_roundtrip", "test_web", "test_http", "test_datadriven",
               "test_mobile", "test_data", "test_report", "test_legacy_import",
               "test_ported_spotcheck", "test_image", "test_apk_sdk", "test_middleware",
               "test_custom_keyword", "test_inner_case", "test_http_files",
               "test_keyword_editor", "test_file_ops", "test_dataconfig_editor",
               "test_suite_testplan", "test_control_editing", "test_clipboard_undo",
               "test_async_run", "test_run_selected", "test_console", "test_search_view",
               "test_mock_server", "test_adb_keywords", "test_office_files",
               "test_unsupported", "test_ios_bootstrap", "test_mobile_backend",
               "test_device_session", "test_parallel_run",
               "test_scheduler", "test_keyword_drag",
               "test_inspector_tree", "test_inspector_panel", "test_stream",
               "test_mirror", "test_web_inspect", "test_ui_structure",
               "test_device_lifecycle", "test_logging", "test_keyword_whitebox",
               "test_keyword_service_sim", "test_ipa",
               # 执行控制 / iOS 组件层 / 平台 lint（2026-07 增补）
               "test_run_control", "test_teardown_interrupt",
               "test_ios_ops", "test_ios_monkey", "test_ios_alert",
               "test_ios_mirror", "test_mirror_stale_recovery",
               "test_case_platform_lint", "test_keyword_platforms",
               "test_mobile_p2_boundaries", "test_device_info", "test_ios_wda_parity",
               "test_ios_parity_diff", "test_android_parity"]


def run_tests() -> tuple[int, int, int, bool]:
    """返回 (通过数, 失败数, 跳过数, 是否被用户中断)。"""
    py = _venv_python(ROOT)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=ROOT)
    p = f = skipped = 0
    suites = discover_test_suites()
    total = len(suites)
    interrupted = False
    proc: subprocess.Popen | None = None
    for i, t in enumerate(suites, 1):
        path = os.path.join(ROOT, "tests", t + ".py")
        if not os.path.isfile(path):
            skipped += 1
            continue
        print(f"  [{i}/{total}] {t} ...", flush=True)
        rc = -1
        stdout = b""
        stderr = b""
        try:
            proc = subprocess.Popen(
                [py, path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=ROOT,
            )
            stdout, stderr = proc.communicate()
            rc = proc.returncode
        except KeyboardInterrupt:
            interrupted = True
            print(f"\n[测试] 用户中断（停在 {t}），正在结束子进程…", flush=True)
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            break
        if rc == 0:
            p += 1
        else:
            f += 1
            print(f"  FAIL: {t}")
            tail = stdout.decode("utf-8", "replace").strip().splitlines()
            if tail:
                print("   ", tail[-3:])
            err = stderr.decode("utf-8", "replace").strip().splitlines()
            if err and not tail:
                print("   ", err[-3:])
    return p, f, skipped, interrupted


def report_device_readiness_violations() -> list[str]:
    """设备判空/容错集中化审计（见 skills/autopilot-lint/check_device_readiness.py）。"""
    lint_dir = os.path.dirname(os.path.abspath(__file__))
    if lint_dir not in sys.path:
        sys.path.insert(0, lint_dir)
    from check_device_readiness import audit_device_readiness  # noqa: PLC0415

    return [v.format() for v in audit_device_readiness(ROOT)]


def report_ui_theme_violations() -> list[str]:
    """UI 主题一致性静态审计（见 skills/autopilot-lint/check_ui_theme.py）。"""
    lint_dir = os.path.dirname(os.path.abspath(__file__))
    if lint_dir not in sys.path:
        sys.path.insert(0, lint_dir)
    from check_ui_theme import audit_ui_theme  # noqa: PLC0415

    return [v.format() for v in audit_ui_theme(ROOT)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-test", action="store_true",
                    help="跳过测试套（仅静态检查/自修，适合 UI 批量改动后快速验收）")
    args = ap.parse_args()

    print("=== AutoPilot 自检/自修 ===")
    xml = fix_xml_empty_tags()
    cf = fix_unused_ctx_and_except()
    sf = fix_signal_emit_noinspection()
    print(f"[自动修复] XML 折叠文件 {xml} 个；源码(ctx/_ctx + broad-except) 改动 {cf} 个文件；"
          f"signal.emit/connect 抑制补全 {sf} 个文件")

    dup_kw = report_duplicate_keyword_ids()
    if dup_kw:
        print(f"[重复关键字id] {len(dup_kw)} 处（XML 内 id 重复，后到覆盖前者）:")
        print("\n".join(dup_kw))
    else:
        print("[重复关键字id] 无")

    bad_imp = report_bad_relative_imports()
    if bad_imp:
        print(f"[相对导入] {len(bad_imp)} 处无法解析（运行到才崩，必须修）:")
        print("\n".join(bad_imp))
    else:
        print("[相对导入] 全部可解析")

    miss = report_missing_noinspection()
    if miss:
        print(f"[需人工确认] {len(miss)} 个 @keyword 函数缺 noinspection（camelCase/内置同名参数）:")
        print("\n".join(miss))
    else:
        print("[需人工确认] 无")

    shadow = report_shadowing()
    if shadow:
        print(f"[作用域遮蔽] {len(shadow)} 处嵌套函数局部名遮蔽外层（PyShadowingNames）:")
        print("\n".join(shadow))
    else:
        print("[作用域遮蔽] 无")

    unused = report_unused_imports()
    if unused:
        print(f"[未用导入] {len(unused)} 处（autopilot + tests，需清理）:")
        print("\n".join(unused))
    else:
        print("[未用导入] 无")

    ruff_ok, ruff_hits = run_ruff()
    if not ruff_ok:
        print("[ruff] 未安装（跳过广度检查；装：.venv/Scripts/python.exe -m pip install ruff）")
    elif ruff_hits:
        print(f"[ruff] {len(ruff_hits)} 处（真错家族，需清理）:")
        print("\n".join(ruff_hits))
    else:
        print("[ruff] 通过")

    android_only = report_android_only_platform_mismatch()
    if android_only:
        print(f"[Android-only 元数据] {len(android_only)} 处不一致（必须修）:")
        print("\n".join(android_only))
    else:
        print("[Android-only 元数据] ANDROID_ONLY_KEYWORD_IDS 与 XML 一致")

    ios_only = report_ios_only_platform_mismatch()
    if ios_only:
        print(f"[iOS-only 元数据] {len(ios_only)} 处不一致（必须修）:")
        print("\n".join(ios_only))
    else:
        print("[iOS-only 元数据] IOS_ONLY_KEYWORD_IDS 与 XML 一致")

    parity_bad = report_parity_skeleton_invalid()
    if parity_bad:
        print(f"[iOS parity 骨架] {len(parity_bad)} 处无效:")
        print("\n".join(parity_bad))
    else:
        print("[iOS parity 骨架] 离线结构 OK")

    parity_diff_bad = report_parity_diff_tool_invalid()
    if parity_diff_bad:
        print(f"[iOS parity diff] {len(parity_diff_bad)} 处无效:")
        print("\n".join(parity_diff_bad))
    else:
        print("[iOS parity diff] 离线自检 OK")

    theme_violations = report_ui_theme_violations()
    if theme_violations:
        print(f"[UI 主题审计] {len(theme_violations)} 处违规（必须修）:")
        print("\n".join(theme_violations))
    else:
        print("[UI 主题审计] 通过")

    device_violations = report_device_readiness_violations()
    if device_violations:
        print(f"[设备容错审计] {len(device_violations)} 处违规（必须修）:")
        print("\n".join(device_violations))
    else:
        print("[设备容错审计] 通过")

    if not args.no_test:
        suites = discover_test_suites()
        print(f"[测试] 运行测试套（共 {len(suites)} 个，ROOT={ROOT}）...")
        p, f, skipped, interrupted = run_tests()
        ran = p + f
        if skipped:
            print(f"[测试] 跳过 {skipped} 个（tests/ 下无对应 .py）")
        if interrupted:
            print(f"[测试] 已中断：已完成 通过 {p} / 失败 {f}")
            return 130
        print(f"[测试] 通过 {p} / 失败 {f}")
        if ran == 0:
            print("[测试] 错误：未实际执行任何测试套（请确认项目根含 tests/）")
            return 1
        if f:
            return 1
    # 未用导入 / 无法解析的相对导入 / ruff 真错 / 重复关键字 id / 平台元数据 / parity → 硬失败
    if unused or bad_imp or dup_kw or android_only or ios_only or parity_bad or parity_diff_bad or theme_violations or device_violations or (ruff_ok and ruff_hits):
        return 1
    print("=== 自检完成 ===")
    return 0


if __name__ == "__main__":
    # noinspection PyBroadException
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n=== 自检已中断（静态检查阶段）===", flush=True)
        raise SystemExit(130)
