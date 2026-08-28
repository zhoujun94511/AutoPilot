"""AutoPilot 主窗口：仅负责组装组件 + 接线信号（薄）。

采用多面板透视图布局。各面板都是 widgets/ 下的独立组件，
主窗口订阅它们的信号、协调业务（打开文件、运行用例），不实现界面细节。
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Optional, cast

from PyQt6.QtCore import Qt, QByteArray, QUrl
from PyQt6.QtWidgets import (
    QMainWindow,
    QDockWidget,
    QStatusBar,
    QStackedWidget,
    QWidget,
    QTabWidget,
    QTabBar,
    QVBoxLayout,
    QHBoxLayout,
    QApplication,
    QMessageBox,
    QMenu,
    QDialog,
)
from PyQt6.QtGui import QAction, QDesktopServices

from ..widgets import (
    ProjectPanel,
    KeywordPanel,
    CaseEditor,
    Console,
    ParamForm,
    MapEditor,
    CustomKeywordEditor,
    DataConfigEditor,
    SuiteEditor,
    TestPlanEditor,
    InspectorPanel,
    MirrorPanel,
    RightAuxiliaryRegion,
    SearchResultsPanel,
    WelcomePanel,
)
from ..widgets.chrome import StatusBarChrome
from ..widgets.chrome.action_builder import (
    build_qactions,
    init_run_control_actions,
    refresh_action_icons,
)
from ..widgets.chrome.editor_run_toolbar import EditorRunToolbar
from ..widgets.chrome.main_toolbar import MainToolbarChrome
from ..widgets.chrome.menu_bar import MenuBarChrome
from ..widgets.chrome.run_control_tips import refresh_run_control_tips
from ..widgets.left_sidebar import LeftSidebar
from ..actions import ACTIONS, EDITOR_CONTEXT_GROUPS
from ..theme import (
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
    apply_main_window,
    apply_panel_theme,
    detect_system_theme,
    effective_theme,
    install_system_theme_listener,
    normalize_stored_theme,
    panel_stylesheet,
    repolish_widget_tree,
)
from ...engine import FaultStrategy
from ...engine.keyword_store import discover_keywords
from .run import RunMixin
from .files import FilesMixin
from .device import DeviceMixin
from .edit import EditMixin
from .mgmt import MgmtMixin
from .authoring import AuthoringMixin
from ...runtime import settings
from ...runtime.log import log_dir
from ...keywords.mobile.appium_server import AppiumServer
from ..branding import app_icon, format_window_title
from ..device_monitor import DeviceMonitor


class MainWindow(QMainWindow, RunMixin, FilesMixin, DeviceMixin, EditMixin, MgmtMixin, AuthoringMixin):
    def __init__(self, project_dir: str = "", config_dir: str = "") -> None:
        super().__init__()
        self.project_dir = project_dir
        self._worker = None                              # 当前异步执行 worker
        self._parallel_running = False                   # 并行批量执行中（禁用单步 F6）
        self._fault_strategy = FaultStrategy.CONTINUE    # 失败策略（#35 可切换）
        self._run_step_count = 0
        self._mgmt_http_worker = None                    # 管理台 HTTP 后台任务
        # 本地执行调度（定时/周期/条件触发）
        self._schedule = None
        self._schedule_runs = 0
        self._schedule_last_passed = None
        self._schedule_gen = 0   # 递增代次：取消/重排后作废已排队的 QTimer
        self._schedule_owned_run = False  # 当前 worker 是否由计划拍启动
        self.setWindowTitle(format_window_title())
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self._ui_theme_stored = settings.ui_theme()

        # ---- 组件实例化 ----
        self.project_panel = ProjectPanel()
        self.project_tree = self.project_panel.tree   # 树仍单独引用，沿用既有逻辑
        self.keyword_panel = KeywordPanel()
        self.case_editor = CaseEditor()
        self.map_editor = MapEditor()
        self.keyword_editor = CustomKeywordEditor()
        self.dataconfig_editor = DataConfigEditor()
        self.suite_editor = SuiteEditor()
        self.testplan_editor = TestPlanEditor()
        self.param_form = ParamForm()
        self.param_form.set_project_dir(project_dir or "")
        self.console = Console()
        self.search_results = SearchResultsPanel()
        self.search_results.set_project_dir(project_dir or "")
        self.inspector = InspectorPanel()
        self.mirror = MirrorPanel()
        self._inspect_ctx = None        # 检视器专用会话上下文
        self._inspect_platform = ""
        self._inspect_chosen = False    # 是否已显式选过检视设备（否则刷新快照前弹选，不默认 Android）
        self._inspect_udid = ""
        self._inspect_wda = ""
        self._ios_backend_mode = settings.ios_backend_mode()
        self._web_engine = settings.web_engine()
        self._http_env_profile = settings.http_env_profile()
        self._inspect_url = ""          # Web 检视目标页面
        self._inspect_browser = settings.web_browser()
        self._appium_server = AppiumServer()   # 仅 Android 控件检视用，按需拉起、关时还原

        self._build_actions()       # 动作注册表 → 单一事实源（菜单/工具栏/右键统一取）
        self._compose_layout()
        self._mount_editor_run_toolbar()
        self._build_menu()
        self._build_toolbar()
        self._wire_signals()
        self._build_statusbar()
        self._sync_ios_backend_controls()
        self._install_editor_context_menus()
        self._default_state = self.saveState()
        self._load_window_layout()
        self._apply_ui_theme(self._ui_theme_stored)
        self._install_system_theme_listener()
        self._maybe_warn_theme_mismatch()

        # ---- 初始数据 ----
        catalog = self.keyword_panel.load(config_dir or None)
        self.catalog = catalog
        # 用例/套件编辑器「关键字」列显示中文名（与关键字库一致，避免显示裸 id）
        self.case_editor.set_catalog(catalog)
        self.suite_editor.set_catalog(catalog)
        has_proj = bool(project_dir) and os.path.isdir(project_dir)
        self.project_panel.set_actions_enabled(has_proj)   # 无工程禁用新建类
        if has_proj:
            self.project_tree.set_root(project_dir)
            self._refresh_custom_keywords()
        self._sync_sidebar_project()
        self._sync_window_title()

    def _sync_sidebar_project(self) -> None:
        if getattr(self, "_left_sidebar", None) is not None:
            self._left_sidebar.set_project_dir(self.project_dir or "")

    def _sync_window_title(self) -> None:
        self.setWindowTitle(format_window_title())

    def _apply_ui_theme(self, stored: str | None = None) -> None:
        """刷新主窗口及已挂载 chrome 面板的 QSS（stored=system|light|dark）。"""
        if stored is None:
            stored = getattr(self, "_ui_theme_stored", THEME_SYSTEM)
        self._ui_theme_stored = normalize_stored_theme(stored)
        theme = effective_theme(self._ui_theme_stored)
        self._ui_theme = theme
        apply_main_window(self, theme)
        if hasattr(self.welcome, "apply_theme"):
            self.welcome.apply_theme(theme)
        else:
            self.welcome.setStyleSheet(panel_stylesheet("text_muted", theme))
        ws = getattr(self, "_editor_workspace", None)
        if ws is not None:
            apply_panel_theme(ws, "editor_workspace", theme)
        if getattr(self, "_left_sidebar", None) is not None:
            self._left_sidebar.apply_theme(theme)
        elif hasattr(self.project_panel, "apply_theme"):
            self.project_panel.apply_theme(theme)
        if getattr(self, "_right_aux", None) is not None:
            self._right_aux.apply_theme(theme)
        if getattr(self, "_status_chrome", None) is not None:
            self._status_chrome.apply_theme(theme)
        if hasattr(self.console, "apply_theme"):
            self.console.apply_theme(theme)
        for widget in (
            self.keyword_panel,
            self.case_editor,
            self.suite_editor,
            self.keyword_editor,
            self.dataconfig_editor,
            self.testplan_editor,
            self.param_form,
            self.inspector,
            self.mirror,
            self.map_editor,
        ):
            if hasattr(widget, "apply_theme"):
                widget.apply_theme(theme)
        menu = getattr(self, "_menu_chrome", None)
        if menu is not None:
            menu.sync_theme_menu(self._ui_theme_stored)
        self._configure_dock_chrome()
        actions = getattr(self, "_actions", None)
        if actions:
            refresh_action_icons(actions, theme)
        repolish_widget_tree(self)

    def _set_ui_theme(self, stored: str) -> None:
        """切换主题偏好并持久化（视图菜单）。"""
        stored = normalize_stored_theme(stored)
        prev_effective = getattr(self, "_ui_theme", None)
        if stored == getattr(self, "_ui_theme_stored", None) and effective_theme(stored) == prev_effective:
            menu = getattr(self, "_menu_chrome", None)
            if menu is not None:
                menu.sync_theme_menu(stored)
            return
        settings.set_ui_theme(stored)
        self._apply_ui_theme(stored)
        labels = {THEME_SYSTEM: "跟随系统", THEME_LIGHT: "浅色", THEME_DARK: "暗色"}
        eff = "暗色" if self._ui_theme == THEME_DARK else "浅色"
        if stored == THEME_SYSTEM:
            msg = f"主题已设为跟随系统（当前：{eff}）"
        else:
            msg = f"已切换为{labels[stored]}主题"
        self.console.log(msg, "视图")

    def _install_system_theme_listener(self) -> None:
        app = cast(QApplication | None, QApplication.instance())
        if app is None or getattr(app, "_autopilot_theme_listener", False):
            return
        install_system_theme_listener(app, self)
        app._autopilot_theme_listener = True  # type: ignore[attr-defined]

    def _maybe_warn_theme_mismatch(self) -> None:
        """存储偏好与系统实际配色不一致时提示（常见于 macOS 自动深色）。"""
        sys_theme = detect_system_theme()
        if self._ui_theme_stored == THEME_LIGHT and sys_theme == THEME_DARK:
            self.console.log(
                "当前为浅色主题，与系统深色不一致；可在「视图 → 主题 → 跟随系统」切换",
                "视图",
            )
        elif self._ui_theme_stored == THEME_DARK and sys_theme == THEME_LIGHT:
            self.console.log(
                "当前为暗色主题，与系统浅色不一致；可在「视图 → 主题 → 跟随系统」切换",
                "视图",
            )

    def _refresh_custom_keywords(self) -> None:
        """扫描工程内自定义关键字(.ks/.ks.yaml)并挂到关键字库的「自定义关键字」分组。"""
        if self.project_dir and os.path.isdir(self.project_dir):
            store = discover_keywords(self.project_dir)
            self._keyword_store = store
            self.keyword_panel.set_custom_keywords(store)
        else:
            self._keyword_store = None

    # ---- 组装 ----
    def _compose_layout(self) -> None:
        # 中央区用堆叠：用例编辑器 / 对象库编辑器 按打开的文件切换
        self.center = QStackedWidget()
        self.center.setObjectName("center_stack")
        self.welcome = WelcomePanel(parent=self)
        self.welcome.open_project_requested.connect(self.open_project)
        self.welcome.open_project_dialog_requested.connect(self.open_project_dialog)
        self.welcome.new_project_dialog_requested.connect(self.new_project_dialog)
        self.welcome.new_case_requested.connect(self.new_case)
        self.center.addWidget(self.welcome)         # 起始/关闭后停靠页
        self.center.addWidget(self.case_editor)
        self.center.addWidget(self.map_editor)
        self.center.addWidget(self.keyword_editor)
        self.center.addWidget(self.dataconfig_editor)
        self.center.addWidget(self.suite_editor)
        self.center.addWidget(self.testplan_editor)
        self.center.setCurrentWidget(self.welcome)
        # 打开文件标签栏（多文件切换）：每个 tab 存该文件的内存模型，切换即重载入对应编辑器。
        # center(堆叠)仍是唯一编辑器载体，故其余逻辑对 self.center 的引用一律不变。
        self._tab_bar = QTabBar()
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setMovable(True)
        self._tab_bar.setDocumentMode(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setUsesScrollButtons(True)
        self._open_docs: list[dict] = []          # 每项 {path,kind,editor,model,title}
        self._switching_tab = False               # 抑制程序性切换触发 currentChanged
        # noinspection PyUnresolvedReferences
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        # noinspection PyUnresolvedReferences
        self._tab_bar.tabCloseRequested.connect(self._on_tab_close)
        self._doc_tab_row = QWidget()
        self._doc_tab_row.setObjectName("doc_tab_row")
        _doc_row_l = QHBoxLayout(self._doc_tab_row)
        _doc_row_l.setContentsMargins(4, 2, 0, 0)
        _doc_row_l.setSpacing(4)
        _doc_row_l.addWidget(self._tab_bar, 1)
        self._editor_run_chrome = None            # _build_actions 后装配
        self._doc_tab_row.hide()                  # 无打开文件时隐藏
        _container = QWidget()
        _container.setObjectName("editor_workspace")
        self._editor_workspace = _container
        _cl = QVBoxLayout(_container)
        _cl.setContentsMargins(0, 0, 0, 0)
        _cl.setSpacing(0)
        _cl.addWidget(self._doc_tab_row)
        _cl.addWidget(self.center, 1)
        self.setCentralWidget(_container)
        self._docks: dict[str, QDockWidget] = {}
        left = Qt.DockWidgetArea.LeftDockWidgetArea
        right = Qt.DockWidgetArea.RightDockWidgetArea
        bottom = Qt.DockWidgetArea.BottomDockWidgetArea
        # 左：侧栏（工程上下文 + 工程树）
        self._left_sidebar = LeftSidebar(self.project_panel)
        d_left = self._add_dock("侧栏", self._left_sidebar, left)
        self._dock_left = d_left
        # 右：单 Dock「右侧辅区」——内嵌上下两组 Tab（编辑 / 设备），避免 4 个 QDock tabify 语义混乱
        self._right_aux = RightAuxiliaryRegion(
            self.keyword_panel, self.param_form, self.inspector, self.mirror,
        )
        d_right = self._add_dock(
            "右侧辅区", self._right_aux, right,
            features=QDockWidget.DockWidgetFeature.DockWidgetClosable,
        )
        self._right_aux_dock = d_right
        # 底：执行控制台 + 查找引用结果（tabify）
        d_console = self._add_dock("执行控制台", self.console, bottom)
        d_search = self._add_dock("查找引用", self.search_results, bottom)
        self.tabifyDockWidget(d_console, d_search)
        d_console.raise_()
        # Tab 标签放到面板「顶部」
        for area in (left, right, bottom):
            self.setTabPosition(area, QTabWidget.TabPosition.North)
        d_left.raise_()
        self._right_aux.activate_view("keyword")
        self._configure_dock_chrome()

    _DOCK_OBJECT_NAMES = {
        "侧栏": "dock_left_sidebar",
        "右侧辅区": "dock_right_aux",
        "执行控制台": "dock_console",
        "查找引用": "dock_find_references",
    }

    def _add_dock(
        self,
        title: str,
        widget: QWidget,
        area: Qt.DockWidgetArea,
        *,
        features: QDockWidget.DockWidgetFeature | None = None,
    ) -> "QDockWidget":
        dock = QDockWidget(title, self)
        dock.setObjectName(self._DOCK_OBJECT_NAMES.get(title, f"dock_{title}"))
        dock.setWidget(widget)
        if features is not None:
            dock.setFeatures(features)
        else:
            # noinspection PyTypeChecker
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetMovable
                | QDockWidget.DockWidgetFeature.DockWidgetClosable
            )
        self.addDockWidget(area, dock)
        self._docks[title] = dock
        return dock

    def _configure_dock_chrome(self) -> None:
        """隐藏 QMainWindow 级 Dock 标签条（与内部 Tab 重复），并启用样式化背景。"""
        for dock in self._docks.values():
            dock.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if dock.titleBarWidget() is None:
                bar = QWidget()
                bar.setFixedHeight(0)
                dock.setTitleBarWidget(bar)

        central = self.centralWidget()
        doc_tab = getattr(self, "_tab_bar", None)
        right_aux = getattr(self, "_right_aux", None)
        for tab_bar in self.findChildren(QTabBar):
            if self._preserve_tab_bar_visible(tab_bar, central=central, doc_tab=doc_tab,
                                               right_aux=right_aux):
                tab_bar.show()
                tab_bar.setMinimumHeight(0)
                tab_bar.setMaximumHeight(16777215)
                continue
            tab_bar.hide()
            tab_bar.setFixedHeight(0)
            tab_bar.setMaximumHeight(0)

    @staticmethod
    def _preserve_tab_bar_visible(
        tab_bar: QWidget,
        *,
        central: QWidget | None,
        doc_tab: QWidget | None,
        right_aux: QWidget | None,
    ) -> bool:
        """保留文档 Tab 与右侧辅区内 ViewTabStack 的 TabBar，勿当作 Dock 级标签折叠。"""
        if tab_bar is doc_tab:
            return True
        parent = tab_bar.parentWidget()
        while parent is not None:
            if right_aux is not None and parent is right_aux:
                return True
            if central is not None and parent is central:
                return True
            parent = parent.parentWidget()
        return False

    def _focus_right_view(self, view_id: str) -> None:
        """显示右侧辅区并切换到指定视图（仅改对应 Tab 组，不抢设备组当前页）。"""
        dock = self._docks.get("右侧辅区")
        if dock is not None:
            dock.show()
            dock.raise_()
        if getattr(self, "_right_aux", None) is not None:
            self._right_aux.activate_view(view_id)

    def _toggle_right_aux(self) -> None:
        dock = self._docks.get("右侧辅区")
        if dock is None:
            return
        dock.setVisible(not dock.isVisible())

    def _load_window_layout(self) -> None:
        st = settings.window_layout_state()
        if st:
            self.restoreState(st)
        aux = settings.right_aux_split_state()
        if aux and getattr(self, "_right_aux", None) is not None:
            self._right_aux.restore_state(QByteArray(aux))

    # ---- 动作注册表 → QAction（单一事实源）----
    def _build_actions(self) -> None:
        self._actions = build_qactions(self, ACTIONS)
        self.act_pause, self.act_stop = init_run_control_actions(self._actions)
        self._toolbar_chrome = MainToolbarChrome(self, self._actions)
        refresh_run_control_tips(self.act_pause, self.act_stop, idle=True)
        self.project_panel.toolbar.set_save_action(self._actions["file.save"])

    def _mount_editor_run_toolbar(self) -> None:
        self._editor_run_chrome = EditorRunToolbar(self._actions, self._doc_tab_row)
        self._doc_tab_row.layout().addWidget(self._editor_run_chrome.widget)

    def _refresh_run_control_tips(self, *, idle: bool) -> None:
        refresh_run_control_tips(self.act_pause, self.act_stop, idle=idle)

    def _build_toolbar(self) -> None:
        """主工具栏已在 _build_actions 中由 MainToolbarChrome 创建。"""
        pass

    def _build_menu(self) -> None:
        self._menu_chrome = MenuBarChrome(self)
        self._recent_menu = self._menu_chrome.recent_menu

    def _fill_recent_menu(self) -> None:
        m = self._recent_menu
        m.clear()
        recents = [p for p in settings.recent_projects() if os.path.isdir(p)]
        if not recents:
            m.addAction("（暂无）").setEnabled(False)
            return
        for p in recents:
            m.addAction(p, lambda _=False, path=p: self.open_project(path))
        m.addSeparator()
        m.addAction("清除列表", self._clear_recent)

    @staticmethod
    def _clear_recent() -> None:
        settings.set_value("recent_projects", [])

    @staticmethod
    def _open_log_dir() -> None:
        path = log_dir()
        # noinspection PyBroadException
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        # noinspection PyUnresolvedReferences
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_monkey_report(self) -> None:
        """打开最近一次 Monkey 报告：优先 HTML，否则打开报告目录。"""
        # 延迟：仅打开 Monkey 报告时需要报告注册表
        from ...mobile.ios.monkey.report_registry import (
            latest_report_dir, latest_report_html,
        )

        proj = (self.project_dir or "").strip()
        if not proj:
            QMessageBox.information(self, "Monkey 报告", "请先打开工程。")
            return
        html = latest_report_html(proj)
        if html and os.path.isfile(html):
            # noinspection PyUnresolvedReferences
            QDesktopServices.openUrl(QUrl.fromLocalFile(html))
            self.console.log(f"已打开 Monkey 报告：{html}", "Monkey")
            return
        path = latest_report_dir(proj)
        if path and os.path.isdir(path):
            # noinspection PyUnresolvedReferences
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            self.console.log(f"已打开 Monkey 报告目录：{path}", "Monkey")
            return
        QMessageBox.information(
            self, "Monkey 报告", "尚无 iOS Monkey 报告，请先执行 mobile_monkey。")

    def _on_edit_params(self, node) -> None:
        """单击/双击步骤的关键字、参数或说明列：仅切到右侧「编辑」组的参数 Tab，不抢设备组。"""
        self._on_step_selected(node)
        self._focus_right_view("param")
        self.param_form.focus_first()

    def _reset_layout(self) -> None:
        if getattr(self, "_default_state", None) is not None:
            self.restoreState(self._default_state)
        for d in self._docks.values():
            d.show()
        aux = getattr(self, "_right_aux", None)
        if aux is not None:
            aux.reset_split()
            aux.activate_view("keyword")
        self.console.log("已重置窗口布局（恢复默认透视图）", "视图")

    def _about(self) -> None:
        import platform
        from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        from ..branding import APP_NAME, APP_VERSION, APP_TAGLINE, app_icon
        from ..widgets.about_dialog import AboutDialog  # 延迟：仅关于对话框
        catalog = getattr(self, "catalog", None)
        total = len(catalog) if catalog else 0
        cats = catalog.categories() if catalog else {}
        cat_str = " / ".join(f"{k} {v}" for k, v in cats.items())
        kw = f"{total}" + (f"（{cat_str}）" if cat_str else "")
        facts = [
            ("平台", "Web · Android · iOS"),
            ("关键字库", kw),
            ("运行环境", f"Python {platform.python_version()} · "
                         f"PyQt {PYQT_VERSION_STR} · Qt {QT_VERSION_STR}"),
        ]
        AboutDialog(app_name=APP_NAME, version=APP_VERSION, tagline=APP_TAGLINE,
                    facts=facts, copyright_text="© 2026 AutoPilot",
                    icon=app_icon(), parent=self,
                    theme=getattr(self, "_ui_theme", None)).exec()

    # ---- 编辑器右键菜单（步骤级动作，与全局工具栏隔离）----
    def _install_editor_context_menus(self) -> None:
        for ed in (self.case_editor, self.suite_editor, self.keyword_editor):
            ed.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            # noinspection PyUnresolvedReferences
            ed.customContextMenuRequested.connect(self._show_editor_context_menu)
        # 工程树右键菜单（新建/重命名/删除/在资源管理器中显示）
        self.project_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.project_tree.customContextMenuRequested.connect(self._show_project_menu)
        # 工程浏览器头部工具条 + 树内键盘（对标 VSCode/PyCharm）
        # noinspection PyUnresolvedReferences
        self.project_panel.newRequested.connect(self._new_resource)
        # noinspection PyUnresolvedReferences
        self.project_panel.newFolderRequested.connect(self._new_folder_dialog)
        # noinspection PyUnresolvedReferences
        self.project_panel.runCheckedRequested.connect(self.run_checked)
        # noinspection PyUnresolvedReferences
        self.project_panel.checkAllRequested.connect(self._on_check_all_requested)
        # noinspection PyUnresolvedReferences
        self.project_tree.renameRequested.connect(self.rename_dialog)
        # noinspection PyUnresolvedReferences
        self.project_tree.deleteRequested.connect(self.delete_dialog)

    def _on_check_all_requested(self, count: int) -> None:
        if count:
            self.console.log(f"当前已勾选 {count} 个用例，可点「批量运行」执行", "工程")
        else:
            self.console.log("当前没有已勾选的用例", "工程")

    def _show_editor_context_menu(self, pos) -> None:
        menu = QMenu(self)
        for gi, group in enumerate(EDITOR_CONTEXT_GROUPS):
            if gi:
                menu.addSeparator()
            for aid in group:
                menu.addAction(self._actions[aid])
        src = self.sender()
        # 调试/编辑：运行至此 + 启用/禁用步骤（用例/套件编辑器专有；方法由 hasattr 运行时守卫）
        # noinspection PyUnresolvedReferences
        if hasattr(src, "toggle_selected_disabled") and src.selected_node() is not None:
            menu.addSeparator()
            menu.addAction(self._actions["run.selected"])
            # noinspection PyUnresolvedReferences
            if hasattr(src, "case_prefix_to_selected") and src.case_prefix_to_selected():
                menu.addAction("运行至此", self.run_to_selected_step)
            # noinspection PyUnresolvedReferences
            node = src.selected_node()
            label = "启用步骤" if getattr(node, "is_run", True) is False else "禁用步骤"
            # noinspection PyUnresolvedReferences
            menu.addAction(label, lambda e=src: e.toggle_selected_disabled())
            from ...model.testcase import Step, StepVerbs  # 延迟：仅右键菜单绑定关键字引用
            ref = ""
            if isinstance(node, StepVerbs):
                ref = f"ks::{node.ks_id}"
            elif isinstance(node, Step) and node.keyword_id:
                ref = node.keyword_id
            if ref:
                menu.addAction(
                    "查找引用",
                    lambda t=ref: self._run_find_references(t))
        # 数据驱动：插入步骤组 / 给选中步骤组绑定数据源（用例编辑器专有）
        if hasattr(src, "insert_stepset"):
            menu.addSeparator()
            # noinspection PyUnresolvedReferences
            menu.addAction("插入步骤组", lambda: src.insert_stepset())
            # noinspection PyUnresolvedReferences
            if src.selected_stepset() is not None:
                # noinspection PyUnresolvedReferences
                menu.addAction("绑定数据源…", lambda e=src: self._bind_stepset_datasource(e))
        # 「移动到段」：把选中的顶层步骤放进前置/主体/后置/异常（用例编辑器专有）
        targets = src.shell_move_targets() if hasattr(src, "shell_move_targets") else []
        if targets:
            menu.addSeparator()
            sub = menu.addMenu("移动到段")
            for name, label in targets:
                act = sub.addAction(label)
                # noinspection PyUnresolvedReferences
                act.triggered.connect(
                    lambda _=False, n=name, e=src: e.move_selected_to_shell(n))
        menu.exec(src.mapToGlobal(pos) if src is not None else self.mapToGlobal(pos))

    def _bind_stepset_datasource(self, editor) -> None:
        """弹数据源对话框，把选中步骤组的 datapool 设为 DATATABLE(...)。"""
        # 延迟：仅绑定数据源时弹窗
        from ..widgets.datasource_dialog import DataSourceDialog
        ss = editor.selected_stepset()
        if ss is None:
            return
        base = getattr(self, "project_dir", "") or ""
        dlg = DataSourceDialog(self, spec=ss.datapool, base_dir=base)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            editor.set_selected_datapool(dlg.spec())

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_chrome = StatusBarChrome(
            sb,
            ios_backend_mode=self._ios_backend_mode,
            web_engine=self._web_engine,
            http_env_profile=self._http_env_profile,
        )
        # 兼容 RunMixin / DeviceMixin 既有属性名
        self.cmb_fault = self._status_chrome.fault.combo
        self.cmb_ios_backend = self._status_chrome.ios_backend.combo
        self.cmb_web_engine = self._status_chrome.web_engine.combo
        self.cmb_http_env = self._status_chrome.http_env.combo
        self._sb_progress = self._status_chrome.progress
        self._sb_device = self._status_chrome.device
        self._sb_pause = self._status_chrome.pause
        self._sb_mc_session = self._status_chrome.mc_session
        self._sb_mc_runner = self._status_chrome.mc_runner
        # noinspection PyUnresolvedReferences
        self.cmb_fault.currentIndexChanged.connect(self._on_fault_changed)
        # noinspection PyUnresolvedReferences
        self.cmb_ios_backend.currentIndexChanged.connect(self._on_ios_backend_changed)
        # noinspection PyUnresolvedReferences
        self.cmb_web_engine.currentIndexChanged.connect(self._on_web_engine_changed)
        # noinspection PyUnresolvedReferences
        self._status_chrome.http_env.profileChanged.connect(self._on_http_env_changed)
        self._status_chrome.wire_device_connect(self.show_device_chip_menu)
        self._mgmt_refresh_session_ui()
        self._devices = ([], [])
        self._gone_timers = {}
        self._gone_grace_s = settings.device_gone_grace_s()
        from ...mobile import ios_bootstrap as _ib  # 延迟：iOS 工具链较重，仅窗口组装时回收残留
        _ib.reclaim_stale_local_ios_prep(
            log=lambda m: self.console.log(m, "设备"))
        self._dev_monitor = DeviceMonitor(interval=3.0)
        # noinspection PyUnresolvedReferences
        self._dev_monitor.changed.connect(self._on_devices_changed)
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            self._dev_monitor.start()
        self._update_device_status()

    def _focus_project_view(self) -> None:
        dock = self._docks.get("侧栏")
        if dock is not None:
            dock.show()
            dock.raise_()

    def _sync_ios_backend_controls(self) -> None:
        """Show the iOS backend / Web engine selectors by project platform."""
        if not hasattr(self, "cmb_ios_backend") and not hasattr(self, "cmb_web_engine"):
            return
        plat = settings.project_platform(self.project_dir) if (self.project_dir and os.path.isdir(self.project_dir)) else ""
        chrome = getattr(self, "_status_chrome", None)
        if chrome is not None:
            if hasattr(chrome, "ios_backend"):
                chrome.ios_backend.set_visible_for_platform(plat)
            if hasattr(chrome, "web_engine"):
                chrome.web_engine.set_visible_for_platform(plat)
            if hasattr(chrome, "http_env"):
                chrome.http_env.set_visible_for_platform(plat)
                chrome.http_env.set_project_dir(self.project_dir or "")

    def _mk_action(self, text: str, slot: Callable[[], None]) -> QAction:
        action = QAction(text, self)
        # noinspection PyUnresolvedReferences
        action.triggered.connect(slot)
        return action

    # ---- 接线 ----
    def _wire_signals(self) -> None:
        # noinspection PyUnresolvedReferences
        self.project_tree.fileActivated.connect(self._on_file_activated)
        # noinspection PyUnresolvedReferences
        self.case_editor.stepSelected.connect(self._on_step_selected)
        # noinspection PyUnresolvedReferences
        self.case_editor.editParamsRequested.connect(self._on_edit_params)
        # noinspection PyUnresolvedReferences
        self.keyword_editor.stepSelected.connect(self._on_step_selected)
        # noinspection PyUnresolvedReferences
        self.suite_editor.stepSelected.connect(self._on_step_selected)
        # noinspection PyUnresolvedReferences
        self.param_form.stepChanged.connect(self.case_editor.refresh_node_row)
        # noinspection PyUnresolvedReferences
        self.param_form.stepChanged.connect(self.keyword_editor.refresh_node_row)
        # noinspection PyUnresolvedReferences
        self.param_form.stepChanged.connect(self.suite_editor.refresh_node_row)
        # noinspection PyUnresolvedReferences
        self.keyword_panel.keywordActivated.connect(self._on_keyword_activated)
        # 拖拽放置：复用与双击相同的插入逻辑（含 ks:: 路由）
        # noinspection PyUnresolvedReferences
        self.case_editor.keywordDropped.connect(self._on_keyword_activated)
        # noinspection PyUnresolvedReferences
        self.suite_editor.keywordDropped.connect(self._on_keyword_activated)
        # noinspection PyUnresolvedReferences
        self.console.stepActivated.connect(self._on_console_step_activated)
        # noinspection PyUnresolvedReferences
        self.search_results.fileActivated.connect(self._on_file_activated)
        # noinspection PyUnresolvedReferences
        self.search_results.searchRequested.connect(self._run_find_references)
        # noinspection PyUnresolvedReferences
        self.keyword_panel.findReferencesRequested.connect(self._run_find_references)
        # noinspection PyUnresolvedReferences
        self.map_editor.findReferencesRequested.connect(self._run_find_references)
        # 控件检视器：静态快照取源 + 落地动作
        self.inspector.snapshot_provider = self._inspector_snapshot
        self.inspector.before_refresh = self._ensure_inspect_device   # 刷新前确认设备（多设备弹选）
        self.inspector.has_session = lambda: getattr(self, "_inspect_ctx", None) is not None
        # noinspection PyUnresolvedReferences
        self.inspector.cancelled.connect(self._on_inspect_cancelled)  # 终止快照→释放设备会话
        # noinspection PyUnresolvedReferences
        self.inspector.fillStep.connect(self._inspector_fill_step)
        # noinspection PyUnresolvedReferences
        self.inspector.addToMap.connect(self._inspector_to_map)
        # noinspection PyUnresolvedReferences
        self.inspector.cropRequested.connect(self._on_inspector_crop)   # 框选→存图→picture:: 定位
        # 实时交互镜像：会话 + 控制汇（与检视器隔离）
        self.mirror.before_start = self._prepare_mirror_start
        self.mirror.session_provider = self._mirror_session
        self._mirror_want_live = False
        self._mirror_control_pending = False
        self._mirror_avf_active = False
        self._mirror_avf_retries = 0
        self._mirror_fallback_mjpeg = False
        self._mirror_cancel = threading.Event()
        self.mirror.video_fallback = self._on_mirror_video_failed
        self.mirror._fail_is_handoff = lambda: getattr(self, "_mirror_control_pending", False)
        # noinspection PyUnresolvedReferences
        self.mirror.videoFirstFrame.connect(self._on_mirror_first_frame)
        # 停止镜像：停高帧采集 + 释放控制会话（与检视器会话解耦）
        # noinspection PyUnresolvedReferences
        self.mirror.sessionEnded.connect(self._on_mirror_stopped)
        self._sync_device_panel_controls()

    def _current_step_editor(self) -> CaseEditor:
        """中央区当前的步骤编辑器（用例/套件/自定义关键字）。"""
        cur = self.center.currentWidget()
        if cur in (self.keyword_editor, self.suite_editor):
            return cast(CaseEditor, cur)
        return self.case_editor

    def _current_case_editor(self) -> Optional[CaseEditor]:
        """当前若是用例或套件编辑器（CaseEditor 系）则返回，否则 None。"""
        cur = self.center.currentWidget()
        if cur in (self.case_editor, self.suite_editor):
            return cast(CaseEditor, cur)
        return None

    def closeEvent(self, event) -> None:
        """关窗即还原：停计划、停实时镜像、退检视会话/WDA 准备、停我们起的 Appium，避免端口残留。"""
        # 先作废计划定时器，避免关窗过程中 tick 再启 worker
        if hasattr(self, "stop_schedule"):
            self.stop_schedule()
        worker = getattr(self, "_worker", None)
        if worker is not None and worker.isRunning():
            worker.request_stop()
            worker.wait(30_000)
            if worker.isRunning():
                self.console.log(
                    "执行线程仍在退出中，已取消关窗；请稍后重试，避免销毁运行中的线程。",
                    "运行",
                    "WARNING",
                )
                event.ignore()
                return

        # 先协作取消慢初始化，再停镜像/等 worker，降低「超时后仍运行却销毁」风险
        # noinspection PyBroadException
        try:
            if hasattr(self, "inspector"):
                self.inspector.cancel_event.set()
                self.inspector._snap_cancelled = True
        except Exception:
            pass
        mirror_cancel = getattr(self, "_mirror_cancel", None)
        if mirror_cancel is not None:
            mirror_cancel.set()
        self._mirror_want_live = False

        # noinspection PyBroadException
        try:
            self.mirror.stop()
        except Exception:
            pass
        # 取消后 prepare 循环会较快退出；给足时间再关窗
        for w in (getattr(self.inspector, "_snap_worker", None),
                  getattr(self, "_ios_sess_worker", None),
                  getattr(self, "_mgmt_http_worker", None)):
            if w is not None and w.isRunning():
                w.wait(12_000)
        if getattr(self, "_dev_monitor", None) is not None:
            # noinspection PyBroadException
            try:
                self._dev_monitor.stop()
            except Exception:
                pass
        self._reset_inspect_session(blocking=True)
        if hasattr(self, "mgmt_stop_local_runner_quiet"):
            self.mgmt_stop_local_runner_quiet()
        settings.set_window_layout_state(bytes(self.saveState().data()))
        if getattr(self, "_right_aux", None) is not None:
            settings.set_right_aux_split_state(bytes(self._right_aux.save_state().data()))
        super().closeEvent(event)
