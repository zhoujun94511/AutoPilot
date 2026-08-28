"""状态栏设备状态：标签 + 可点击 Chip（与失败策略 / iOS 后端同一套布局）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import apply_panel_theme, icon_color
from ..actions import qicon


class DeviceStatusChip(QPushButton):
    """设备连接状态按钮（状态栏控件带内嵌）。"""

    connectRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("device_status_chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self._theme = "light"
        self.apply_theme(self._theme)
        self.set_status("idle", "未连接设备", "点击查看已连接设备 / 连接检视")
        # noinspection PyUnresolvedReferences
        self.clicked.connect(self.connectRequested)

    def apply_theme(self, theme: str) -> None:
        self._theme = apply_panel_theme(self, "device_chip", theme)
        ic = qicon("mdi6.cellphone-link", color=icon_color("tool", self._theme))
        if ic is not None:
            self.setIcon(ic)

    def set_status(self, state: str, text: str, tooltip: str = "") -> None:
        """state: idle | detected | connected"""
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText(text)
        if tooltip:
            self.setToolTip(tooltip)


class DeviceStatusField(QWidget):
    """与失败策略 / iOS 后端同构：左侧标签 + 右侧控件。"""

    connectRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("status_bar_field")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(QLabel("设备"))
        self.chip = DeviceStatusChip(self)
        # noinspection PyUnresolvedReferences
        self.chip.connectRequested.connect(self.connectRequested)
        lay.addWidget(self.chip)

    def apply_theme(self, theme: str) -> None:
        self.chip.apply_theme(theme)

    def set_status(self, state: str, text: str, tooltip: str = "") -> None:
        self.chip.set_status(state, text, tooltip)

    def text(self) -> str:
        return self.chip.text()

    def status_state(self) -> str:
        return str(self.chip.property("state") or "")
