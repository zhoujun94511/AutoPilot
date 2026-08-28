"""菜单栏 chrome：从 actions.MENUS 构建标准菜单 + 视图/帮助扩展。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import QMenu, QMenuBar

from ...actions import MENUS
from ...theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM

if TYPE_CHECKING:
    from ...main_window.window import MainWindow

_DOCK_TOGGLE_TITLES = ("侧栏", "右侧辅区", "执行控制台")
_RIGHT_VIEWS = (
    ("keyword", "关键字库"),
    ("param", "参数"),
    ("inspector", "控件检视器"),
    ("mirror", "实时镜像"),
)


def _host_slot(host: "MainWindow", name: str):
    """菜单槽：经 getattr 解析，避免 chrome 层直接访问 protected 成员名。"""
    return getattr(host, name)


def fill_menu_from_rows(menu: QMenu, rows: tuple, actions: dict[str, QAction]) -> None:
    """按 actions.MENUS 行描述填充菜单（支持分隔符与子菜单）。"""
    for row in rows:
        if row is None:
            menu.addSeparator()
        elif isinstance(row, tuple) and row[0] == "submenu":
            _, sub_title, ids = row
            sub = menu.addMenu(sub_title)
            for aid in ids:
                sub.addAction(actions[aid])
        else:
            menu.addAction(actions[row])


def make_menu_action(parent, text: str, slot) -> QAction:
    act = QAction(text, parent)
    # noinspection PyUnresolvedReferences
    act.triggered.connect(slot)
    return act


class MenuBarChrome:
    """装配主窗口菜单栏；动态「最近工程」子菜单通过 recent_menu 暴露。"""

    def __init__(self, host: "MainWindow") -> None:
        self._host = host
        self.recent_menu: QMenu | None = None
        self._theme_actions: dict[str, QAction] = {}
        self._build(host.menuBar(), getattr(host, "_actions", {}))

    def _build(self, bar: QMenuBar, actions: dict[str, QAction]) -> None:
        host = self._host
        for title, rows in MENUS:
            menu = bar.addMenu(title)
            fill_menu_from_rows(menu, rows, actions)
            if title.startswith("文件"):
                self.recent_menu = menu.addMenu("打开最近工程")
                # noinspection PyUnresolvedReferences
                self.recent_menu.aboutToShow.connect(_host_slot(host, "_fill_recent_menu"))
        self._build_view_menu(bar, actions)
        self._build_help_menu(bar)

    def _build_view_menu(self, bar: QMenuBar, actions: dict[str, QAction]) -> None:
        host = self._host
        docks = getattr(host, "_docks", {})
        m = bar.addMenu("视图(&V)")
        for title in _DOCK_TOGGLE_TITLES:
            dock = docks.get(title)
            if dock is not None:
                m.addAction(dock.toggleViewAction())
        m.addSeparator()
        if "view.focus_project" in actions:
            m.addAction(actions["view.focus_project"])
        else:
            m.addAction("工程", _host_slot(host, "_focus_project_view"))
        sub_right = m.addMenu("右侧视图")
        focus_right = _host_slot(host, "_focus_right_view")
        for view_id, label in _RIGHT_VIEWS:
            sub_right.addAction(label, lambda _=False, v=view_id: focus_right(v))
        m.addSeparator()
        act_toggle = make_menu_action(
            host, "显示/隐藏右侧辅区", _host_slot(host, "_toggle_right_aux"))
        act_toggle.setShortcut(QKeySequence("Ctrl+Alt+R"))
        m.addAction(act_toggle)
        m.addAction(make_menu_action(host, "重置窗口布局", _host_slot(host, "_reset_layout")))
        m.addSeparator()
        self._build_theme_menu(m, host)

    def _build_theme_menu(self, view_menu: QMenu, host: "MainWindow") -> None:
        sub = view_menu.addMenu("主题")
        group = QActionGroup(host)
        group.setExclusive(True)
        self._theme_actions = {}
        for theme_id, label in (
            (THEME_SYSTEM, "跟随系统"),
            (THEME_LIGHT, "浅色"),
            (THEME_DARK, "暗色"),
        ):
            act = QAction(label, host)
            act.setCheckable(True)
            group.addAction(act)
            # noinspection PyUnresolvedReferences
            act.triggered.connect(
                lambda _checked=False, t=theme_id: _host_slot(host, "_set_ui_theme")(t))
            sub.addAction(act)
            self._theme_actions[theme_id] = act
        self.sync_theme_menu(getattr(host, "_ui_theme_stored", THEME_SYSTEM))

    def sync_theme_menu(self, theme: str) -> None:
        for theme_id, act in self._theme_actions.items():
            act.setChecked(theme_id == theme)

    def _build_help_menu(self, bar: QMenuBar) -> None:
        host = self._host
        m = bar.addMenu("帮助(&H)")
        m.addAction(make_menu_action(host, "打开日志文件夹", _host_slot(host, "_open_log_dir")))
        m.addAction(make_menu_action(
            host, "打开 Monkey 报告", _host_slot(host, "_open_monkey_report")))
        m.addSeparator()
        m.addAction(make_menu_action(host, "关于 AutoPilot", _host_slot(host, "_about")))
