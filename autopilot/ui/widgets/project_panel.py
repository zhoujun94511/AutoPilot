"""工程浏览器面板：工具条组件 + 筛选 + 工程树。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLineEdit

from .chrome.project_toolbar import ProjectExplorerToolbar
from .project_tree import ProjectTree


class ProjectPanel(QWidget):
    newRequested = pyqtSignal(str)
    newFolderRequested = pyqtSignal()
    runCheckedRequested = pyqtSignal(list)
    checkAllRequested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("project_panel")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        from ..theme import init_panel_style

        init_panel_style(self, "project_panel")

        self.tree = ProjectTree()
        self.toolbar = ProjectExplorerToolbar(self)
        # noinspection PyUnresolvedReferences
        self.toolbar.newRequested.connect(self.newRequested)
        # noinspection PyUnresolvedReferences
        self.toolbar.newFolderRequested.connect(self.newFolderRequested)
        self.toolbar.refreshRequested.connect(self.tree.refresh)
        self.toolbar.collapseRequested.connect(self.tree.collapse_subdirs)
        self.toolbar.toggleChecksRequested.connect(self._on_toggle_checks)
        self.toolbar.batchRunRequested.connect(self._on_batch_run)
        v.addWidget(self.toolbar)
        self.filter = QLineEdit()
        self.filter.setObjectName("project_filter")
        self.filter.setPlaceholderText("筛选文件名…")
        self.filter.setClearButtonEnabled(True)
        v.addWidget(self.filter)
        v.addWidget(self.tree, 1)

        # noinspection PyUnresolvedReferences
        self.filter.textChanged.connect(self.tree.set_name_filter)
        self.tree.checkedChanged.connect(self._sync_batch_run_btn)

    def _on_toggle_checks(self) -> None:
        n = self.tree.invert_visible_checks()
        self._sync_batch_run_btn()
        # noinspection PyUnresolvedReferences
        self.checkAllRequested.emit(n)

    def _on_batch_run(self) -> None:
        paths = self.tree.checked_paths()
        if paths:
            # noinspection PyUnresolvedReferences
            self.runCheckedRequested.emit(paths)

    def _sync_batch_run_btn(self) -> None:
        self.toolbar.set_batch_run_count(len(self.tree.checked_paths()))

    def set_actions_enabled(self, on: bool) -> None:
        self.toolbar.set_project_actions_enabled(on)

    @property
    def btn_run(self):
        return self.toolbar.btn_batch_run

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme

        apply_panel_theme(self, "project_panel", theme)
        self.toolbar.apply_theme(theme)
        self.tree.viewport().update()
