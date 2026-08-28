"""工程浏览器头部工具条（新建/刷新/勾选/批量运行）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QMenu, QToolButton

from .icon_tool_button import IconToolButton
from ...theme import apply_panel_theme, init_panel_style

_NEW_ITEMS = (
    ("case", "用例"),
    ("suite", "测试套"),
    ("map", "对象库"),
    ("dataconfig", "数据配置"),
    ("testplan", "测试计划"),
    ("keyword", "自定义关键字"),
)
_TOGGLE_CHECKS_TIP = (
    "全选/反选：对当前可见用例切换勾选"
    "（全未勾≈全选，全勾≈清空，部分勾选时反选）"
)


class ProjectExplorerToolbar(QWidget):
    """工程树上方工具条；业务动作以信号交出。"""

    newRequested = pyqtSignal(str)
    newFolderRequested = pyqtSignal()
    refreshRequested = pyqtSignal()
    collapseRequested = pyqtSignal()
    toggleChecksRequested = pyqtSignal()
    batchRunRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("project_toolbar")
        bar = QHBoxLayout(self)
        bar.setContentsMargins(8, 8, 4, 2)
        bar.setSpacing(2)

        self.btn_new = IconToolButton.create(
            "mdi6.plus", "在工程中新建…", label="新建",
            object_name="project_new_btn",
        )
        self._new_menu = QMenu(self)
        for kind, label in _NEW_ITEMS:
            act = self._new_menu.addAction(f"{label}…")
            # noinspection PyUnresolvedReferences
            act.triggered.connect(lambda _=False, k=kind: self.newRequested.emit(k))
        # noinspection PyUnresolvedReferences
        self.btn_new.clicked.connect(self._show_new_menu)

        self.btn_folder = IconToolButton.create(
            "mdi6.folder-plus-outline", "新建文件夹", label="目录")
        self.btn_refresh = IconToolButton.create(
            "mdi6.refresh", "重新扫描磁盘并刷新工程树", label="刷新")
        self.btn_collapse = IconToolButton.create(
            "mdi6.collapse-all-outline", "折叠所有子目录（工程根保持可见）", label="折叠")
        self.btn_toggle_checks = IconToolButton.create(
            "mdi6.checkbox-multiple-marked-outline",
            _TOGGLE_CHECKS_TIP, label="全/反")

        for b in (
            self.btn_new, self.btn_folder, self.btn_refresh, self.btn_collapse,
            self.btn_toggle_checks,
        ):
            bar.addWidget(b)
        bar.addStretch(1)

        self.btn_save = QToolButton()
        self.btn_save.setObjectName("project_save_btn")
        self.btn_save.setAutoRaise(True)
        self.btn_save.setEnabled(False)
        bar.addWidget(self.btn_save)

        self.btn_batch_run = IconToolButton.create(
            "mdi6.play-circle-outline",
            "请先在用例行左侧打勾，再批量运行",
            label="批量运行",
            object_name="batch_run_btn",
            icon_tone="tool_on_tint",
        )
        self.btn_batch_run.setEnabled(False)
        bar.addWidget(self.btn_batch_run)

        init_panel_style(self, "project_panel")
        self._icon_buttons = (
            self.btn_new, self.btn_folder, self.btn_refresh, self.btn_collapse,
            self.btn_toggle_checks, self.btn_batch_run,
        )

        # noinspection PyUnresolvedReferences
        self.btn_folder.clicked.connect(self.newFolderRequested)
        self.btn_refresh.clicked.connect(self.refreshRequested)
        self.btn_collapse.clicked.connect(self.collapseRequested)
        self.btn_toggle_checks.clicked.connect(self.toggleChecksRequested)
        self.btn_batch_run.clicked.connect(self.batchRunRequested)

    def _show_new_menu(self) -> None:
        if not self.btn_new.isEnabled():
            return
        self._new_menu.exec(
            self.btn_new.mapToGlobal(self.btn_new.rect().bottomLeft()))

    def set_project_actions_enabled(self, on: bool) -> None:
        self.btn_new.setEnabled(on)
        self.btn_folder.setEnabled(on)
        self.btn_toggle_checks.setEnabled(on)
        tip_on = "在工程中新建…"
        tip_off = "请先「新建工程」或「打开工程」"
        self.btn_new.setToolTip(tip_on if on else tip_off)
        self.btn_folder.setToolTip("新建文件夹" if on else tip_off)
        self.btn_toggle_checks.setToolTip(_TOGGLE_CHECKS_TIP if on else tip_off)

    def set_save_action(self, action: QAction) -> None:
        """绑定全局「保存」QAction（图标/快捷键/启用态与菜单一致）。"""
        self.btn_save.setDefaultAction(action)

    def set_batch_run_count(self, count: int) -> None:
        self.btn_batch_run.setEnabled(count > 0)
        self.btn_batch_run.setText(
            f"批量运行({count})" if count else "批量运行")
        self.btn_batch_run.setToolTip(
            f"批量运行已勾选的 {count} 个用例并生成报告" if count
            else "请先在用例行左侧打勾，再批量运行")

    def apply_theme(self, theme: str) -> None:
        apply_panel_theme(self, "project_panel", theme)
        for btn in self._icon_buttons:
            tone = "tool_on_tint" if btn is self.btn_batch_run else "tool"
            IconToolButton.apply_theme(btn, theme, tone)
