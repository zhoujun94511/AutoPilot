"""UI 主题一致性静态审计（无 Qt 运行时依赖）。

防止浅色/暗色迭代时出现：QSS 键名漂移、palette(mid) 回潮、面板未接 apply_theme、
首帧写死 light、程序化着色绕过 semantic_color 等回归。

用法（项目根下）：
    .venv/bin/python skills/autopilot-lint/check_ui_theme.py
    .venv/bin/python skills/autopilot-lint/check_ui_theme.py -v

亦被 skills/autopilot-lint/autocheck.py 在静态检查阶段调用（硬失败）。
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    detail: str
    line: int | None = None

    def format(self) -> str:
        loc = f":{self.line}" if self.line else ""
        return f"[{self.rule}] {self.path}{loc} — {self.detail}"


# panel_stylesheet(name) 的 name → 文档用（init 检查见 _init_checks）
_INIT_PANEL_STYLE: dict[str, tuple[str, ...]] = {
    "project_panel": ("ProjectPanel",),
    "sidebar_context": ("SidebarContextBar",),
    "form_editor": ("CustomKeywordEditor", "DataConfigEditor", "TestPlanEditor"),

    "inspector_panel": ("InspectorPanel",),
    "map_editor": ("MapEditor",),
}

# 主窗口 _apply_ui_theme 应刷新的面板（类名, 相对 autopilot/ui 的路径片段）
_REQUIRE_APPLY_THEME: tuple[tuple[str, str], ...] = (
    ("WelcomePanel", "widgets/welcome_panel.py"),
    ("KeywordPanel", "widgets/keyword_panel.py"),
    ("CaseEditor", "widgets/case_editor.py"),
    ("CustomKeywordEditor", "widgets/keyword_editor.py"),
    ("DataConfigEditor", "widgets/dataconfig_editor.py"),
    ("TestPlanEditor", "widgets/testplan_editor.py"),
    ("ParamForm", "widgets/param_form.py"),
    ("InspectorPanel", "widgets/inspector_panel.py"),
    ("MirrorPanel", "widgets/mirror_panel.py"),
    ("MapEditor", "widgets/map_editor.py"),
    ("Console", "widgets/console.py"),
    ("ProjectPanel", "widgets/project_panel.py"),
    ("LeftSidebar", "widgets/left_sidebar.py"),
    ("RightAuxiliaryRegion", "widgets/auxiliary_region.py"),
)

# setForeground(QColor("#...")) 允许的文件（检视器绘图层、品牌资源等）
_SETFOREGROUND_HEX_ALLOW = frozenset({
    "autopilot/ui/branding.py",
})

# 禁止再次出现的「旧版硬编码语义色」（应走 theme.semantic_color）
_BANNED_HEX_IN_WIDGETS = (
    "#566573",
    "#8893a6",
    "#37474f",
)

# 使用 QTableWidget 表头时，对应 panel QSS 须显式写 QHeaderView（Dock 内不继承壳层）
_TABLE_HEADER_PANEL_QSS: tuple[tuple[str, str, str], ...] = (
    ("autopilot/ui/widgets/ai_authoring_dialog.py", "setHorizontalHeaderLabels", "AI_AUTHORING_DIALOG_QSS"),
    ("autopilot/ui/widgets/console.py", "setHorizontalHeaderLabels", "CONSOLE_QSS"),
    ("autopilot/ui/widgets/inspector_panel.py", "setHorizontalHeaderLabels", "INSPECTOR_PANEL_QSS"),
    ("autopilot/ui/widgets/case_editor.py", "horizontalHeader", "CASE_EDITOR_QSS"),
    ("autopilot/ui/widgets/keyword_editor.py", "horizontalHeader", "FORM_EDITOR_QSS"),
    ("autopilot/ui/widgets/dataconfig_editor.py", "horizontalHeader", "FORM_EDITOR_QSS"),
    ("autopilot/ui/widgets/testplan_editor.py", "horizontalHeader", "FORM_EDITOR_QSS"),
)

# Dock 内面板 setStyleSheet 后不再继承 MAIN_WINDOW_SHELL，须自带 chrome 控件样式
_DOCK_PANEL_CHROME_QSS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("CONSOLE_QSS", ("QHeaderView::section", "QLabel", "QTableCornerButton::section")),
    ("INSPECTOR_PANEL_QSS", ("QHeaderView::section", "QLabel", "QPushButton", "QTableWidget::item")),
    ("MIRROR_PANEL_QSS", ("QLabel", "QPushButton", "QToolButton", "QLineEdit")),
    ("AUXILIARY_TOOLBAR_QSS", ("QWidget#auxiliary_region_toolbar",)),
    ("CASE_EDITOR_QSS", ("QHeaderView::section",)),
    ("FORM_EDITOR_QSS", ("QHeaderView::section",)),
)

# 面板根 objectName 须有实色 background（避免透出 Dock/系统暗色）
_ROOT_SURFACE_QSS: tuple[tuple[str, str], ...] = (
    ("WELCOME_PANEL_QSS", "QWidget#welcome_panel"),
    ("AI_AUTHORING_DIALOG_QSS", "QDialog#ai_authoring_dialog"),
    ("CONSOLE_QSS", "QWidget#autopilot_console"),
    ("INSPECTOR_PANEL_QSS", "QWidget#inspector_panel"),
    ("LEFT_SIDEBAR_QSS", "QWidget#left_sidebar"),
    ("AUXILIARY_REGION_QSS", "QWidget#right_auxiliary_region"),
    ("AUXILIARY_TOOLBAR_QSS", "QWidget#auxiliary_region_toolbar"),
    ("SIDEBAR_CONTEXT_QSS", "QWidget#sidebar_context"),
)

# QGraphicsView + EmptyState 须设置 scene 背景（默认场景为黑色方块）
_GRAPHICS_SCENE_FILES = (
    "autopilot/ui/widgets/inspector_panel.py",
    "autopilot/ui/widgets/mirror_panel.py",
)

# widgets 内 qicon 无 color 参数（文件类型色等除外）
_QICON_COLOR_ALLOW = frozenset({
    "autopilot/ui/branding.py",
    "autopilot/ui/widgets/project_tree.py",
    "autopilot/ui/actions.py",
})

_QICON_BARE_RE = re.compile(r"""qicon\(\s*['"][^'"]+['"]\s*\)""")

# widgets 内 setStyleSheet 允许的文件（动态定位符 chip 等）
_SETSTYLESHEET_ALLOW = frozenset({
    "autopilot/ui/widgets/inspector_panel.py",
})

# widgets 内禁止 palette(
_PALETTE_ALLOW = frozenset({
    "autopilot/ui/widgets/grip_splitter.py",  # 若存在则允许；实际无 palette
})

_QSS_EXPORT_RE = re.compile(r"^([A-Z][A-Z0-9_]*_QSS)\s*=", re.MULTILINE)
_PANEL_MAP_RE = re.compile(r'"([a-z_]+)":\s*mod\.([A-Z][A-Z0-9_]*_QSS)')
_THEME_CALL_NAME_ARG = {
    "apply_panel_theme": 1,
    "init_panel_style": 1,
    "apply_dialog_theme": 1,
    "panel_stylesheet": 0,
}


def _find_project_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    if os.path.isdir(os.path.join(root, "autopilot")):
        return root
    return os.getcwd()


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def _read(root: str, rel_path: str) -> str:
    return open(os.path.join(root, rel_path), encoding="utf-8").read()


def _line_of(text: str, needle: str) -> int | None:
    for i, ln in enumerate(text.splitlines(), 1):
        if needle in ln:
            return i
    return None


def _qss_exports(text: str) -> set[str]:
    return set(_QSS_EXPORT_RE.findall(text))


def _ast_const_value(node: ast.AST) -> object | None:
    """读取 ``ast.Constant`` 字面量；用 getattr 避开 IDE 对 ``Constant.value`` 的误报。"""
    if isinstance(node, ast.Constant):
        return getattr(node, "value", None)
    return None


def _class_has_method(path: str, class_name: str, method: str) -> bool:
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return any(
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == method
                for child in node.body
            )
    return False


def _class_init_calls_init_panel(
    path: str, class_name: str, panel_name: str,
) -> bool:
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        init = next(
            (c for c in node.body
             if isinstance(c, ast.FunctionDef) and c.name == "__init__"),
            None,
        )
        if init is None:
            return False
        for sub in ast.walk(cast(ast.AST, init)):
            if not isinstance(sub, ast.Call):
                continue
            if getattr(sub.func, "id", None) == "init_panel_style":
                if len(sub.args) >= 2:
                    if _ast_const_value(sub.args[1]) == panel_name:
                        return True
            if getattr(sub.func, "attr", None) == "init_panel_style":
                if len(sub.args) >= 2:
                    if _ast_const_value(sub.args[1]) == panel_name:
                        return True
    return False


def audit_ui_theme(root: str | None = None) -> list[Violation]:
    """运行全部主题规则，返回违规列表（空 = 通过）。"""
    root = root or _find_project_root()
    ui = os.path.join(root, "autopilot", "ui")
    theme_dir = os.path.join(ui, "theme")
    violations: list[Violation] = []

    light_path = os.path.join(theme_dir, "qss_light.py")
    dark_path = os.path.join(theme_dir, "qss_dark.py")
    init_path = os.path.join(theme_dir, "__init__.py")
    light_text = open(light_path, encoding="utf-8").read()
    dark_text = open(dark_path, encoding="utf-8").read()
    init_text = open(init_path, encoding="utf-8").read()

    # --- QSS 导出键名一一对应 ---
    light_keys = _qss_exports(light_text)
    dark_keys = _qss_exports(dark_text)
    for key in sorted(light_keys - dark_keys):
        violations.append(Violation(
            "qss_keys_parity", "autopilot/ui/theme/qss_dark.py",
            f"缺少与浅色同名的 {key}",
        ))
    for key in sorted(dark_keys - light_keys):
        violations.append(Violation(
            "qss_keys_parity", "autopilot/ui/theme/qss_light.py",
            f"缺少与暗色同名的 {key}",
        ))

    # --- 禁止 palette()（macOS 上与自定义壳层不一致）---
    for rel, text in (
        ("autopilot/ui/theme/qss_light.py", light_text),
        ("autopilot/ui/theme/qss_dark.py", dark_text),
    ):
        for i, ln in enumerate(text.splitlines(), 1):
            if "palette(" in ln and not ln.strip().startswith("#"):
                violations.append(Violation(
                    "qss_no_palette", rel,
                    f"勿用 palette()，请改固定色值或 semantic_color: {ln.strip()[:80]}",
                    i,
                ))

    # --- panel_stylesheet 映射 ↔ QSS 片段非空 ---
    panel_map = dict(_PANEL_MAP_RE.findall(init_text))

    def _qss_body(qss_text: str, const_name: str) -> str | None:
        """解析 QSS 常量体；支持 \"\"\"...\"\"\" 与同文件别名。"""
        hit = re.search(rf"^{re.escape(const_name)}\s*=\s*\"\"\"", qss_text, re.M)
        if hit:
            chunk = qss_text[hit.end():]
            end = chunk.find('"""')
            return chunk[:end].strip() if end >= 0 else ""
        alias = re.search(
            rf"^{re.escape(const_name)}\s*=\s*([A-Z][A-Z0-9_]*)\s*$", qss_text, re.M)
        if alias:
            return _qss_body(qss_text, alias.group(1))
        return None

    for name, const in sorted(panel_map.items()):
        for rel, theme_text in (
            ("autopilot/ui/theme/qss_light.py", light_text),
            ("autopilot/ui/theme/qss_dark.py", dark_text),
        ):
            body = _qss_body(theme_text, const)
            if body is None:
                violations.append(Violation(
                    "panel_qss_defined", rel,
                    f"panel_stylesheet 键 {name!r} 引用的 {const} 未定义",
                ))
            elif not body:
                violations.append(Violation(
                    "panel_qss_nonempty", rel,
                    f"{const}（panel {name!r}）不应为空",
                ))

    # --- 主题 API 的字面量名称必须已注册（防止拼写错误静默返回空 QSS）---
    for dirpath, _, files in os.walk(ui):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                call_name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute) else ""
                )
                arg_index = _THEME_CALL_NAME_ARG.get(call_name)
                if arg_index is None or len(node.args) <= arg_index:
                    continue
                arg = node.args[arg_index]
                name = _ast_const_value(arg)
                if not isinstance(name, str):
                    continue
                if name not in panel_map:
                    violations.append(Violation(
                        "panel_style_registered",
                        _rel(root, path),
                        f"{call_name} 使用了未注册主题名 {name!r}",
                        node.lineno,
                    ))

    _surface_checks = (
        ("CASE_EDITOR_QSS", "QTableWidget#case_editor", "background"),
        ("KEYWORD_PANEL_QSS", "QTreeWidget#keyword_tree", "background"),
        ("PROJECT_PANEL_QSS", "QTreeView#project_tree", "background"),
        ("EDITOR_WORKSPACE_QSS", "QWidget#editor_workspace", "background"),
        ("INSPECTOR_PANEL_QSS", "QWidget#inspector_panel", "background"),
        ("CONSOLE_QSS", "QWidget#autopilot_console", "background"),
        ("AUXILIARY_TOOLBAR_QSS", "QWidget#auxiliary_region_toolbar", "background"),
    )
    for const, selector, prop in _surface_checks:
        for rel, text in (
            ("autopilot/ui/theme/qss_light.py", light_text),
            ("autopilot/ui/theme/qss_dark.py", dark_text),
        ):
            body = _qss_body(text, const) or ""
            if selector not in body or prop not in body:
                violations.append(Violation(
                    "qss_surface_parity", rel,
                    f"{const} 须含 {selector} 的 {prop}（浅/暗切换时避免残留）",
                ))

    # --- 壳层 QSS 覆盖 SpinBox / CheckBox ---
    for rel, text in (
        ("autopilot/ui/theme/qss_light.py", light_text),
        ("autopilot/ui/theme/qss_dark.py", dark_text),
    ):
        shell_m = re.search(r"MAIN_WINDOW_SHELL_QSS\s*=\s*\"\"\"(.*?)\"\"\"", text, re.S)
        if shell_m is None:
            violations.append(Violation("shell_qss", rel, "缺少 MAIN_WINDOW_SHELL_QSS"))
            continue
        shell = shell_m.group(1)
        for ctrl in ("QSpinBox", "QCheckBox"):
            if ctrl not in shell:
                violations.append(Violation(
                    "shell_controls", rel,
                    f"MAIN_WINDOW_SHELL_QSS 应包含 {ctrl}（表单控件深浅色一致）",
                ))
        for dock_id in ("dock_left_sidebar", "dock_right_aux", "dock_console"):
            if dock_id not in shell:
                violations.append(Violation(
                    "dock_chrome_qss", rel,
                    f"MAIN_WINDOW_SHELL_QSS 应样式化 QDockWidget#{dock_id}",
                ))
        sb_m = re.search(r"QStatusBar\s*\{([^}]+)}", shell, re.S)
        if sb_m is None:
            violations.append(Violation(
                "statusbar_qss", rel,
                "MAIN_WINDOW_SHELL_QSS 应样式化 QStatusBar",
            ))
        elif rel == "autopilot/ui/theme/qss_light.py":
            sb_body = sb_m.group(1)
            if "#007acc" in sb_body:
                violations.append(Violation(
                    "statusbar_no_vscode_blue", rel,
                    "浅色 QStatusBar 勿用 #007acc，应与壳层中性灰 #f3f3f3 一致",
                ))
            if "border-top" not in sb_body:
                violations.append(Violation(
                    "statusbar_border", rel,
                    "浅色 QStatusBar 应有 border-top 与上方 Dock 分隔",
                ))

    # --- 侧栏顶栏禁止透明透出 Dock 底色 ---
    for const in ("SIDEBAR_CONTEXT_QSS",):
        for rel, text in (
            ("autopilot/ui/theme/qss_light.py", light_text),
            ("autopilot/ui/theme/qss_dark.py", dark_text),
        ):
            body = _qss_body(text, const) or ""
            if "background: transparent" in body or "background-color: transparent" in body:
                violations.append(Violation(
                    "sidebar_opaque_bg", rel,
                    f"{const} 禁止 transparent 背景（会透出 Dock 标签条暗色）",
                ))

    # --- Dock 面板 QSS 禁止 transparent（普通对话框/欢迎页允许透明子控件）---
    dock_panel_consts = {
        "CONSOLE_QSS", "INSPECTOR_PANEL_QSS", "MIRROR_PANEL_QSS",
        "PROJECT_PANEL_QSS",
        "SIDEBAR_CONTEXT_QSS", "LEFT_SIDEBAR_QSS",
        "AUXILIARY_REGION_QSS", "AUXILIARY_TOOLBAR_QSS",
    }
    for const in sorted(dock_panel_consts):
        for rel, text in (
            ("autopilot/ui/theme/qss_light.py", light_text),
            ("autopilot/ui/theme/qss_dark.py", dark_text),
        ):
            body = _qss_body(text, const) or ""
            if "transparent" in body:
                violations.append(Violation(
                    "panel_no_transparent", rel,
                    f"{const} 含 transparent，Dock 内面板会深浅混搭",
                ))

    # --- 表头：有 QTableWidget 表头的面板 QSS 须写 QHeaderView::section ---
    for rel_path, needle, const in _TABLE_HEADER_PANEL_QSS:
        wpath = os.path.join(root, rel_path)
        if not os.path.isfile(wpath):
            continue
        wtext = open(wpath, encoding="utf-8").read()
        if needle not in wtext:
            continue
        for theme_rel, text in (
            ("autopilot/ui/theme/qss_light.py", light_text),
            ("autopilot/ui/theme/qss_dark.py", dark_text),
        ):
            body = _qss_body(text, const) or ""
            if "QHeaderView::section" not in body:
                violations.append(Violation(
                    "table_header_qss", theme_rel,
                    f"{const} 须含 QHeaderView::section（{rel_path} 使用表头）",
                ))

    # --- Dock 内面板 chrome 控件（QLabel/QPushButton/表头/工具条容器）---
    for const, selectors in _DOCK_PANEL_CHROME_QSS:
        for theme_rel, text in (
            ("autopilot/ui/theme/qss_light.py", light_text),
            ("autopilot/ui/theme/qss_dark.py", dark_text),
        ):
            body = _qss_body(text, const) or ""
            for sel in selectors:
                if sel not in body:
                    violations.append(Violation(
                        "dock_panel_chrome", theme_rel,
                        f"{const} 须含 {sel}（面板 QSS 不继承壳层）",
                    ))

    # --- 面板根表面实色 background ---
    for const, selector in _ROOT_SURFACE_QSS:
        for theme_rel, text in (
            ("autopilot/ui/theme/qss_light.py", light_text),
            ("autopilot/ui/theme/qss_dark.py", dark_text),
        ):
            body = _qss_body(text, const) or ""
            if selector not in body or "background" not in body.split(selector, 1)[-1][:120]:
                violations.append(Violation(
                    "panel_root_surface", theme_rel,
                    f"{const} 须为 {selector} 设置实色 background",
                ))

    # --- QGraphicsScene 默认黑底：检视/镜像须 setBackgroundBrush 或 apply_scene_theme ---
    for rel_path in _GRAPHICS_SCENE_FILES:
        path = os.path.join(root, rel_path)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        if "QGraphicsScene" not in text and "QGraphicsView" not in text:
            continue
        if "setBackgroundBrush" not in text and "apply_scene_theme" not in text:
            violations.append(Violation(
                "graphics_scene_bg", rel_path,
                "QGraphicsView 须 setBackgroundBrush/apply_scene_theme，避免空态黑块",
            ))

    # --- 右侧辅区内嵌 Tab 须显式主题化 ---
    for rel, text in (
        ("autopilot/ui/theme/qss_light.py", light_text),
        ("autopilot/ui/theme/qss_dark.py", dark_text),
    ):
        body = _qss_body(text, "AUXILIARY_REGION_QSS") or ""
        if "QTabBar::tab" not in body:
            violations.append(Violation(
                "aux_tabbar_qss", rel,
                "AUXILIARY_REGION_QSS 须含 QTabBar::tab（Dock 内 Tab 不继承壳层 QSS）",
            ))

    # --- 语义色表 light/dark 键一致 ---
    for block_name in ("_SEMANTIC", "_ICON_COLORS", "_LEVEL_COLORS", "_STATUS_COLORS"):
        pattern = (
            rf"{re.escape(block_name)}:\s*dict\[str,\s*dict\[str,\s*str]]\s*=\s*"
            r"(\{.*?\n})"
        )
        m = re.search(pattern, init_text, re.S)
        if m is None:
            violations.append(Violation(
                "semantic_tables", "autopilot/ui/theme/__init__.py",
                f"缺少 {block_name} 定义",
            ))
            continue
        block = m.group(1)
        light_m = re.search(r"THEME_LIGHT:\s*\{([^}]+)}", block, re.S)
        dark_m = re.search(r"THEME_DARK:\s*\{([^}]+)}", block, re.S)
        if not light_m or not dark_m:
            continue
        light_keys_inner = set(re.findall(r'"([^"]+)"\s*:', light_m.group(1)))
        dark_keys_inner = set(re.findall(r'"([^"]+)"\s*:', dark_m.group(1)))
        if light_keys_inner != dark_keys_inner:
            violations.append(Violation(
                "semantic_keys_parity", "autopilot/ui/theme/__init__.py",
                f"{block_name} 的 light/dark 键不一致: "
                f"仅浅色={sorted(light_keys_inner - dark_keys_inner)} "
                f"仅暗色={sorted(dark_keys_inner - light_keys_inner)}",
            ))

    # --- 默认跟随系统 + 主窗口监听 ---
    if 'DEFAULT_THEME = THEME_SYSTEM' not in init_text:
        violations.append(Violation(
            "default_theme_system", "autopilot/ui/theme/__init__.py",
            "DEFAULT_THEME 应为 THEME_SYSTEM",
        ))
    if "def icon_color(" not in init_text:
        violations.append(Violation(
            "icon_color_api", "autopilot/ui/theme/__init__.py",
            "须提供 icon_color() 统一工具栏/导航图标色",
        ))
    icon_tb = open(
        os.path.join(ui, "widgets", "chrome", "icon_tool_button.py"),
        encoding="utf-8",
    ).read()
    if "icon_color" not in icon_tb:
        violations.append(Violation(
            "icon_tool_button_theme", "autopilot/ui/widgets/chrome/icon_tool_button.py",
            "IconToolButton 须通过 theme.icon_color 着色图标",
        ))
    action_builder = open(
        os.path.join(ui, "widgets", "chrome", "action_builder.py"),
        encoding="utf-8",
    ).read()
    if "icon_color" not in action_builder:
        violations.append(Violation(
            "action_builder_icons", "autopilot/ui/widgets/chrome/action_builder.py",
            "build_qactions 须通过 icon_color 着色菜单/工具栏图标",
        ))
    window_path = os.path.join(ui, "main_window", "window.py")
    window_text = open(window_path, encoding="utf-8").read()
    if "_install_system_theme_listener" not in window_text:
        violations.append(Violation(
            "system_theme_listener", "autopilot/ui/main_window/window.py",
            "MainWindow 应安装 _install_system_theme_listener",
        ))
    if "_configure_dock_chrome" not in window_text:
        violations.append(Violation(
            "dock_chrome_helper", "autopilot/ui/main_window/window.py",
            "MainWindow 应实现 _configure_dock_chrome 隐藏冗余 Dock 标签条",
        ))
    elif "_preserve_tab_bar_visible" not in window_text:
        violations.append(Violation(
            "dock_chrome_preserve_aux_tabs", "autopilot/ui/main_window/window.py",
            "_configure_dock_chrome 须保留右侧辅区 ViewTabStack 的 TabBar 可见",
        ))
    if "configure_application_theme" not in init_text:
        violations.append(Violation(
            "app_palette_theme", "autopilot/ui/theme/__init__.py",
            "须实现 configure_application_theme（Fusion + QPalette，macOS 系统深色隔离）",
        ))
    elif "configure_application_theme(theme)" not in init_text:
        violations.append(Violation(
            "app_palette_wired", "autopilot/ui/theme/__init__.py",
            "apply_main_window 应调用 configure_application_theme",
        ))

    # --- grip_splitter 相对导入层级 ---
    grip_path = os.path.join(ui, "widgets", "grip_splitter.py")
    grip_text = open(grip_path, encoding="utf-8").read()
    if "...theme" in grip_text:
        violations.append(Violation(
            "grip_import", "autopilot/ui/widgets/grip_splitter.py",
            "应使用 from ..theme import（勿用 ...theme 越过 ui 包）",
            _line_of(grip_text, "...theme"),
        ))

    # --- 面板 apply_theme ---
    for class_name, rel_suffix in _REQUIRE_APPLY_THEME:
        path = os.path.join(ui, rel_suffix)
        if not os.path.isfile(path):
            violations.append(Violation(
                "apply_theme_missing_file", f"autopilot/ui/{rel_suffix}",
                f"规则期望的源文件不存在（{class_name}）",
            ))
            continue
        if not _class_has_method(path, class_name, "apply_theme"):
            violations.append(Violation(
                "apply_theme_required", f"autopilot/ui/{rel_suffix}",
                f"{class_name} 须实现 apply_theme(theme)",
            ))
        else:
            src = open(path, encoding="utf-8").read()
            apply_m = re.search(
                r"def apply_theme\(self, theme: str.*?\n(?P<abody>(?:.*?\n)*?)"
                r"(?=\n\s{4}def |\n\s{4}@|\nclass |\Z)",
                src, re.S,
            )
            body = apply_m.group("abody") if apply_m else ""
            delegates = ".apply_theme(theme)" in body
            resolves = (
                "resolve_theme" in body
                or "effective_theme" in body
                or "apply_panel_theme" in body
            )
            if body and not resolves and not delegates:
                violations.append(Violation(
                    "apply_theme_resolve", f"autopilot/ui/{rel_suffix}",
                    f"{class_name}.apply_theme 应解析主题或委托子组件 apply_theme",
                ))

    # --- init_panel_style 首帧 ---
    _init_checks: list[tuple[str, str, str]] = [
        ("project_panel", "widgets/project_panel.py", "ProjectPanel"),
        ("sidebar_context", "widgets/sidebar_header.py", "SidebarContextBar"),
        ("form_editor", "widgets/keyword_editor.py", "CustomKeywordEditor"),
        ("form_editor", "widgets/dataconfig_editor.py", "DataConfigEditor"),
        ("form_editor", "widgets/testplan_editor.py", "TestPlanEditor"),
        ("param_form", "widgets/param_form.py", "ParamForm"),
        ("keyword_panel", "widgets/keyword_panel.py", "KeywordPanel"),
        ("inspector_panel", "widgets/inspector_panel.py", "InspectorPanel"),
        ("map_editor", "widgets/map_editor.py", "MapEditor"),
        ("auxiliary_toolbar", "widgets/chrome/auxiliary_toolbar.py", "AuxiliaryRegionToolbar"),
        ("empty_state", "widgets/empty_state.py", "EmptyState"),
        ("welcome_panel", "widgets/welcome_panel.py", "WelcomePanel"),
    ]
    for panel_name, rel_suffix, class_name in _init_checks:
        path = os.path.join(ui, rel_suffix)
        if not _class_init_calls_init_panel(path, class_name, panel_name):
            violations.append(Violation(
                "init_panel_style", f"autopilot/ui/{rel_suffix}",
                f"{class_name}.__init__ 应调用 init_panel_style(self, {panel_name!r})",
            ))

    # --- widgets 目录：写死 _ui_theme、旧语义色、裸 setForeground ---
    widgets_root = os.path.join(ui, "widgets")
    for dirpath, _, files in os.walk(widgets_root):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = _rel(root, path)
            text = open(path, encoding="utf-8").read()
            for i, ln in enumerate(text.splitlines(), 1):
                stripped = ln.strip()
                if stripped.startswith("#"):
                    continue
                if re.search(r'_ui_theme\s*=\s*["\'](?:light|dark)["\']', ln):
                    violations.append(Violation(
                        "hardcoded_ui_theme", rel,
                        "勿写死 _ui_theme；用 init_panel_style 或 effective_theme(settings.ui_theme())",
                        i,
                    ))
                for hx in _BANNED_HEX_IN_WIDGETS:
                    if hx in ln.lower() and "semantic_color" not in ln:
                        violations.append(Violation(
                            "banned_semantic_hex", rel,
                            f"硬编码语义色 {hx}；请用 theme.semantic_color(...)",
                            i,
                        ))
                if (
                    "setForeground" in ln
                    and 'QColor("#' in ln.replace(" ", "")
                    and rel not in _SETFOREGROUND_HEX_ALLOW
                    and "semantic_color" not in ln
                    and "level_color" not in ln
                    and "status_color" not in ln
                    and "_row_color" not in ln
                    and "_fg(" not in ln
                ):
                    violations.append(Violation(
                        "setforeground_hex", rel,
                        "setForeground(QColor(\"#...\")) 应改 semantic_color/level_color 或加入允许列表",
                        i,
                    ))
                if "palette(" in ln and rel not in _PALETTE_ALLOW:
                    violations.append(Violation(
                        "widgets_no_palette", rel,
                        "widgets 勿用 palette() 取色；用 theme.semantic_color 或 QSS",
                        i,
                    ))
                if ".setStyleSheet(" in ln and rel not in _SETSTYLESHEET_ALLOW:
                    if "apply_panel_theme" not in ln and "panel_stylesheet" not in ln:
                        violations.append(Violation(
                            "widgets_setstylesheet", rel,
                            "setStyleSheet 应经 apply_panel_theme/panel_stylesheet（apply_theme 内）",
                            i,
                        ))
                if (
                    rel not in _QICON_COLOR_ALLOW
                    and "qicon(" in ln
                    and "color=" not in ln.replace(" ", "")
                    and _QICON_BARE_RE.search(ln)
                ):
                    violations.append(Violation(
                        "qicon_missing_color", rel,
                        "qicon() 须传 color= 或走 icon_color()（浅色底上默认图标不可见）",
                        i,
                    ))

    # --- console 勿再定义本地 _LEVEL_COLOR 字典 ---
    console_text = open(os.path.join(ui, "widgets", "console.py"), encoding="utf-8").read()
    if re.search(r"^_LEVEL_COLOR\s*=", console_text, re.M):
        violations.append(Violation(
            "console_level_colors", "autopilot/ui/widgets/console.py",
            "级别色应走 theme.level_color，勿维护本地 _LEVEL_COLOR",
        ))
    if re.search(r"^_STATUS_COLOR\s*=", console_text, re.M):
        violations.append(Violation(
            "console_status_colors", "autopilot/ui/widgets/console.py",
            "状态色应走 theme.status_color，勿维护本地 _STATUS_COLOR",
        ))

    return violations


def main(argv: list[str] | None = None) -> int:
    # noinspection PyBroadException
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="UI 主题一致性静态审计")
    ap.add_argument("-v", "--verbose", action="store_true", help="通过时也打印规则摘要")
    args = ap.parse_args(argv)

    root = _find_project_root()
    violations = audit_ui_theme(root)

    if violations:
        print(f"UI 主题审计: ❌ {len(violations)} 处违规\n")
        for v in violations:
            print(v.format())
        return 1

    print("UI 主题审计: ✅ 通过（QSS 键名、Dock chrome、表头、透明底、graphics scene、apply_theme）")
    if args.verbose:
        print(f"  根目录: {root}")
        print("  规则: qss_keys_parity, dock_panel_chrome, table_header_qss,")
        print("        panel_no_transparent, panel_root_surface, graphics_scene_bg,")
        print("        apply_theme_*, init_panel_style, widgets_setstylesheet, …")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
