"""加宽拖动手柄、悬停高亮的 QSplitter（拖动时实时预览）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QSplitter, QSplitterHandle


_HANDLE_PX = 10


def _grip_qcolors() -> tuple[QColor, QColor, QColor]:
    from ..theme import grip_palette

    track, hover, border = grip_palette()
    return QColor(track), QColor(hover), QColor(border)


class GripSplitterHandle(QSplitterHandle):
    """分割条手柄：加宽轨道 + 悬停高亮。"""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._hover = False
        if orientation == Qt.Orientation.Horizontal:
            self.setCursor(Qt.CursorShape.SplitHCursor)
            self.setMinimumWidth(_HANDLE_PX)
        else:
            self.setCursor(Qt.CursorShape.SplitVCursor)
            self.setMinimumHeight(_HANDLE_PX)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        track_c, hover_c, border_c = _grip_qcolors()
        p = QPainter(self)
        track = hover_c if self._hover else track_c
        p.fillRect(self.rect(), track)
        p.setPen(border_c)
        if self.orientation() == Qt.Orientation.Horizontal:
            p.drawLine(0, 0, 0, self.height())
            p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        else:
            p.drawLine(0, 0, self.width(), 0)
            p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class GripSplitter(QSplitter):
    """可发现、易拖拽的分割容器。"""

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent=None,
        *,
        handle_px: int = _HANDLE_PX,
        tooltip: str = "",
    ) -> None:
        super().__init__(orientation, parent)
        self.setHandleWidth(handle_px)
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)
        if not tooltip:
            tooltip = (
                "拖动此处左右调整列宽"
                if orientation == Qt.Orientation.Horizontal
                else "拖动此处上下调整区域高度"
            )
        self._handle_tooltip = tooltip

    def createHandle(self) -> QSplitterHandle:
        handle = GripSplitterHandle(self.orientation(), self)
        handle.setToolTip(self._handle_tooltip)
        return handle


# 分隔条 QSS 已迁入 theme/qss_*.py 的 MAIN_WINDOW_SHELL_QSS
