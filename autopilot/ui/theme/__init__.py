"""IDE 主题：集中管理 QSS；支持跟随 macOS / Windows 系统深浅色。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from . import qss_dark, qss_light
from ...runtime import settings

THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_SYSTEM = "system"
DEFAULT_THEME = THEME_SYSTEM
STORED_THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget


def normalize_stored_theme(theme: str | None) -> str:
    """合法存储值：system | light | dark。"""
    value = (theme or DEFAULT_THEME).strip().lower()
    if value in STORED_THEMES:
        return value
    return DEFAULT_THEME


def detect_system_theme() -> str:
    """读取 Qt 当前系统配色（macOS 自动浅色/深色）。"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    app = cast("QApplication", QApplication.instance())
    if app is None:
        return THEME_LIGHT
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return THEME_DARK
    return THEME_LIGHT


def effective_theme(stored: str | None = None) -> str:
    """将存储偏好解析为实际应用的 light | dark。"""
    stored = normalize_stored_theme(stored)
    if stored == THEME_SYSTEM:
        return detect_system_theme()
    return stored


def resolve_theme(theme: str | None) -> str:
    """兼容旧调用：等同于 effective_theme。"""
    return effective_theme(theme)


def _qss_module(theme: str):
    return qss_dark if theme == THEME_DARK else qss_light


def configure_application_theme(theme: str) -> None:
    """应用级主题：Fusion 样式 + QPalette，避免 macOS 系统深色污染未写 QSS 的控件。

    仅给主窗口/面板 setStyleSheet 时，ComboBox/ToolButton/表头角标等仍会走系统 palette；
    与 QSS 一并设置后才是完整「一致化」。
    """
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QApplication, QStyleFactory

    app = cast("QApplication", QApplication.instance())
    if app is None:
        return
    if app.style().objectName().lower() != "fusion":
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            app.setStyle(fusion)

    colors = _APP_PALETTE[theme]
    pal = QPalette()
    for role, hex_color in colors.items():
        pal.setColor(role, QColor(hex_color))
    app.setPalette(pal)


_APP_PALETTE: dict[str, dict] = {}


def _build_app_palettes() -> None:
    from PyQt6.QtGui import QPalette

    _APP_PALETTE[THEME_LIGHT] = {
        QPalette.ColorRole.Window: "#f3f3f3",
        QPalette.ColorRole.WindowText: "#212121",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f5f6f8",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#212121",
        QPalette.ColorRole.Text: "#212121",
        QPalette.ColorRole.Button: "#fafafa",
        QPalette.ColorRole.ButtonText: "#212121",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Link: "#1565c0",
        QPalette.ColorRole.Highlight: "#e3f2fd",
        QPalette.ColorRole.HighlightedText: "#000000",
        QPalette.ColorRole.Mid: "#757575",
        QPalette.ColorRole.Dark: "#bdbdbd",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Shadow: "#9e9e9e",
    }
    _APP_PALETTE[THEME_DARK] = {
        QPalette.ColorRole.Window: "#1e1e1e",
        QPalette.ColorRole.WindowText: "#e0e0e0",
        QPalette.ColorRole.Base: "#1e1e1e",
        QPalette.ColorRole.AlternateBase: "#252526",
        QPalette.ColorRole.ToolTipBase: "#2d2d2d",
        QPalette.ColorRole.ToolTipText: "#e0e0e0",
        QPalette.ColorRole.Text: "#e0e0e0",
        QPalette.ColorRole.Button: "#2d2d2d",
        QPalette.ColorRole.ButtonText: "#e0e0e0",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Link: "#64b5f6",
        QPalette.ColorRole.Highlight: "#264f78",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Mid: "#9e9e9e",
        QPalette.ColorRole.Dark: "#3c3c3c",
        QPalette.ColorRole.Light: "#505050",
        QPalette.ColorRole.Shadow: "#1e1e1e",
    }


_build_app_palettes()


def main_window_stylesheet(theme: str = THEME_LIGHT) -> str:
    """主窗口级 QSS（壳层 + 工具栏）；theme 须为 light | dark。"""
    mod = _qss_module(theme)
    return mod.MAIN_WINDOW_SHELL_QSS + mod.TOOLBAR_QSS


def apply_main_window(window: "QMainWindow", theme: str = THEME_LIGHT) -> None:
    configure_application_theme(theme)
    configure_grip_theme(theme)
    window.setStyleSheet(main_window_stylesheet(theme))


def apply_panel_theme(widget: "QWidget", name: str, theme: str | None = None) -> str:
    """为面板套上 QSS 并强制重绘（切换主题时避免 macOS viewport 残留）。"""
    resolved = effective_theme(theme)
    widget.setStyleSheet(panel_stylesheet(name, resolved))
    repolish_widget_tree(widget)
    return resolved


def repolish_widget_tree(root: "QWidget") -> None:
    """主题切换后强制重绘样式树（避免 Qt/macOS 残留上一主题的 viewport 色）。"""
    from PyQt6.QtWidgets import QWidget

    for widget in (root, *root.findChildren(QWidget)):
        # 每次现取：polish 过程中 Qt 可能重建 QStyleSheetStyle 代理，
        # 缓存住的指针会在循环中途失效 → 访问越界崩溃（规则越多越易触发）。
        style = widget.style()
        if style is None:
            continue
        style.unpolish(widget)
        style.polish(widget)
        widget.update()


_GRIP_PALETTES = {
    THEME_LIGHT: ("#eceff1", "#e3f2fd", "#cfd8dc"),
    THEME_DARK: ("#3c3c3c", "#505050", "#2d2d2d"),
}
_grip_palette: tuple[str, str, str] = _GRIP_PALETTES[THEME_LIGHT]


def configure_grip_theme(theme: str) -> None:
    """同步 GripSplitter 手绘分割条颜色（右侧辅区等）。"""
    global _grip_palette
    _grip_palette = _GRIP_PALETTES.get(theme, _GRIP_PALETTES[THEME_LIGHT])


def grip_palette() -> tuple[str, str, str]:
    return _grip_palette


# 程序化着色（表格行/树节点/控制台级别）——与 QSS 语义一致
_SEMANTIC: dict[str, dict[str, str]] = {
    THEME_LIGHT: {
        "disabled": "#9e9e9e",
        "muted": "#566573",
        "shell_muted": "#8a8a8a",
        "group_fg": "#37474f",
        "id_fg": "#8893a6",
        "desc_fg": "#8a8a8a",
        "hint": "#616161",
        "mid": "#757575",
        "placeholder": "#616161",
    },
    THEME_DARK: {
        "disabled": "#6e6e6e",
        "muted": "#9e9e9e",
        "shell_muted": "#757575",
        "group_fg": "#b0bec5",
        "id_fg": "#78909c",
        "desc_fg": "#9e9e9e",
        "hint": "#bdbdbd",
        "mid": "#9e9e9e",
        "placeholder": "#9e9e9e",
    },
}

_ICON_COLORS: dict[str, dict[str, str]] = {
    THEME_LIGHT: {
        "tool": "#455a64",
        "tool_on_tint": "#283593",
        "nav": "#546e7a",
        "nav_active": "#1565c0",
        "warn": "#e65100",
        "tree_folder": "#607d8b",
        "tree_keyword": "#1565c0",
        "tree_star": "#f9a825",
    },
    THEME_DARK: {
        "tool": "#b0bec5",
        "tool_on_tint": "#90caf9",
        "nav": "#9e9e9e",
        "nav_active": "#64b5f6",
        "warn": "#ffb74d",
        "tree_folder": "#90a4ae",
        "tree_keyword": "#64b5f6",
        "tree_star": "#ffca28",
    },
}

_LEVEL_COLORS: dict[str, dict[str, str]] = {
    THEME_LIGHT: {
        "DEBUG": "#9e9e9e",
        "INFO": "#1565c0",
        "WARNING": "#ff9800",
        "ERROR": "#e53935",
        "CRITICAL": "#b71c1c",
    },
    THEME_DARK: {
        "DEBUG": "#757575",
        "INFO": "#64b5f6",
        "WARNING": "#ffb74d",
        "ERROR": "#ef5350",
        "CRITICAL": "#e57373",
    },
}

_STATUS_COLORS: dict[str, dict[str, str]] = {
    THEME_LIGHT: {
        "PASS": "#4caf50",
        "FAIL": "#e53935",
        "NOIMPL": "#ff9800",
        "SKIP": "#9e9e9e",
        "LOG": "#1565c0",
    },
    THEME_DARK: {
        "PASS": "#81c784",
        "FAIL": "#ef5350",
        "NOIMPL": "#ffb74d",
        "SKIP": "#9e9e9e",
        "LOG": "#64b5f6",
    },
}


def semantic_color(key: str, theme: str | None = None) -> str:
    """取弱化/禁用等语义色（theme 为 light | dark 或存储偏好）。"""
    pool = _SEMANTIC[effective_theme(theme)]
    return pool.get(key, "#9e9e9e")


def icon_color(tone: str, theme: str | None = None) -> str:
    """工具栏/导航图标色（qtawesome 须显式传色，否则浅色底上几乎不可见）。"""
    pool = _ICON_COLORS[effective_theme(theme)]
    return pool.get(tone, pool["tool"])


def level_color(level: str, theme: str | None = None) -> str | None:
    """控制台日志级别色；未知级别返回 None。"""
    return _LEVEL_COLORS[effective_theme(theme)].get(level)


def status_color(status: str, theme: str | None = None) -> str | None:
    """控制台步骤状态色；未知状态返回 None。"""
    return _STATUS_COLORS[effective_theme(theme)].get(status)


def init_panel_style(widget, name: str) -> str:
    """组件 __init__ 时按当前偏好套上 panel QSS，避免首帧浅色闪屏。"""
    return apply_panel_theme(widget, name, settings.ui_theme())


def _panel_mapping(mod) -> dict[str, str]:
    """面板/对话框名 → QSS；浅色/深色模块须暴露同名 ``*_QSS`` 常量。"""
    return {
        "project_panel": mod.PROJECT_PANEL_QSS,
        "sidebar_header": mod.SIDEBAR_HEADER_QSS,
        "sidebar_context": mod.SIDEBAR_CONTEXT_QSS,
        "device_chip": mod.DEVICE_CHIP_QSS,
        "auxiliary_toolbar": mod.AUXILIARY_TOOLBAR_QSS,
        "text_muted": mod.TEXT_MUTED_QSS,
        "keyword_panel": mod.KEYWORD_PANEL_QSS,
        "case_editor": mod.CASE_EDITOR_QSS,
        "form_editor": mod.FORM_EDITOR_QSS,
        "empty_state": mod.EMPTY_STATE_QSS,
        "param_form": mod.PARAM_FORM_QSS,
        "map_editor": mod.MAP_EDITOR_QSS,
        "inspector_panel": mod.INSPECTOR_PANEL_QSS,
        "mirror_panel": mod.MIRROR_PANEL_QSS,
        "auxiliary_region": mod.AUXILIARY_REGION_QSS,
        "left_sidebar": mod.LEFT_SIDEBAR_QSS,
        "editor_workspace": mod.EDITOR_WORKSPACE_QSS,
        "welcome_panel": mod.WELCOME_PANEL_QSS,
        "ai_authoring_dialog": mod.AI_AUTHORING_DIALOG_QSS,
        "about_dialog": mod.ABOUT_DIALOG_QSS,
        "dialog_form": mod.DIALOG_FORM_QSS,
        "login_gate": mod.LOGIN_GATE_QSS,
        "console": mod.CONSOLE_QSS,
    }


def registered_panel_names() -> frozenset[str]:
    """已注册的主题样式名（调用 ``apply_*_theme`` / ``init_panel_style`` 时必须用这里的名字）。"""
    return frozenset(_panel_mapping(qss_light))


def panel_stylesheet(name: str, theme: str = THEME_LIGHT) -> str:
    """按面板名取 QSS 片段；未知名称立即失败，避免界面静默退化为无样式。"""
    mapping = _panel_mapping(_qss_module(theme))
    try:
        return mapping[name]
    except KeyError as exc:
        known = ", ".join(sorted(mapping))
        raise ValueError(f"未知主题样式名：{name!r}；可用名称：{known}") from exc


def resolve_dialog_theme(widget=None, theme: str | None = None) -> str:
    """对话框取主题：显式参数 > 父窗口 _ui_theme > settings。"""
    if theme:
        return effective_theme(theme)
    if widget is not None:
        parent = widget.parent()
        ui_theme = getattr(parent, "_ui_theme", None) if parent is not None else None
        if ui_theme is not None:
            return effective_theme(ui_theme)
    return effective_theme(settings.ui_theme())


def apply_dialog_theme(dialog, name: str, theme: str | None = None) -> str:
    """为对话框应用 QSS 片段，返回实际使用的主题名。"""
    resolved = resolve_dialog_theme(dialog, theme)
    dialog.setStyleSheet(panel_stylesheet(name, resolved))
    return resolved


def install_system_theme_listener(app: "QApplication", window: "QMainWindow") -> None:
    """macOS 系统深浅色切换时，若偏好为「跟随系统」则自动刷新。"""
    from PyQt6.QtCore import Qt

    hints = app.styleHints()

    def _on_scheme_changed(_scheme: Qt.ColorScheme) -> None:
        if settings.ui_theme() != THEME_SYSTEM:
            return
        apply_theme = getattr(window, "_apply_ui_theme", None)
        if apply_theme is not None:
            apply_theme(THEME_SYSTEM)

    # noinspection PyUnresolvedReferences
    hints.colorSchemeChanged.connect(_on_scheme_changed)
