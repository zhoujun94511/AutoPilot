"""带 id 的 Tab 视图堆叠（右侧辅区等）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget


class ViewTabStack(QWidget):
    """QTabWidget 封装：按 view_id 切换，便于主窗口/菜单统一调度。"""

    viewActivated = pyqtSignal(str)

    def __init__(
        self,
        tabs: tuple[tuple[str, str, QWidget], ...],
        *,
        parent=None,
    ) -> None:
        """tabs: (view_id, label, widget)"""
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._tabs = QTabWidget()
        self._tabs.setObjectName("aux_view_tab_stack")
        self._tabs.setDocumentMode(True)
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._tabs.tabBar().setObjectName("aux_view_tab_bar")
        self._index_to_id: list[str] = []
        for view_id, label, widget in tabs:
            self._tabs.addTab(widget, label)
            self._index_to_id.append(view_id)
        lay.addWidget(self._tabs)
        # noinspection PyUnresolvedReferences
        self._tabs.currentChanged.connect(self._on_changed)

    def _on_changed(self, index: int) -> None:
        if 0 <= index < len(self._index_to_id):
            # noinspection PyUnresolvedReferences
            self.viewActivated.emit(self._index_to_id[index])

    def activate(self, view_id: str) -> None:
        try:
            idx = self._index_to_id.index(view_id)
        except ValueError:
            return
        self._tabs.setCurrentIndex(idx)

    def current_view_id(self) -> str:
        idx = self._tabs.currentIndex()
        if 0 <= idx < len(self._index_to_id):
            return self._index_to_id[idx]
        return ""

    def tab_index(self) -> int:
        return self._tabs.currentIndex()
