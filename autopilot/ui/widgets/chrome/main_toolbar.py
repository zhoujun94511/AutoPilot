"""主窗口全局工具栏装配（可为空；运行控件见 EditorRunToolbar）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMainWindow, QToolBar

from ...actions import TOOLBAR_GROUPS


class MainToolbarChrome:
    """从已构建的 QAction 字典创建主工具栏；无分组时不创建工具栏。"""

    def __init__(self, window: QMainWindow, actions: dict[str, QAction]) -> None:
        self._actions = actions
        self.toolbar: QToolBar | None = None
        if not any(TOOLBAR_GROUPS):
            return
        self.toolbar = QToolBar("主工具栏", window)
        self.toolbar.setObjectName("main_toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        for gi, group in enumerate(TOOLBAR_GROUPS):
            if gi:
                self.toolbar.addSeparator()
            for aid in group:
                self.toolbar.addAction(actions[aid])
        window.addToolBar(self.toolbar)

    @property
    def act_pause(self) -> QAction:
        return self._actions["run.pause"]

    @property
    def act_stop(self) -> QAction:
        return self._actions["run.stop"]
