"""右侧辅区顶栏（标题 + 分割控制）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel

from ...theme import init_panel_style
from .icon_tool_button import IconToolButton


class AuxiliaryRegionToolbar(QWidget):
    expandDeviceRequested = pyqtSignal()
    resetSplitRequested = pyqtSignal()

    def __init__(self, title: str = "右侧辅区", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("auxiliary_region_toolbar")
        bar = QHBoxLayout(self)
        bar.setContentsMargins(6, 4, 6, 2)
        bar.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("auxiliary_region_title")
        self._title_label = lbl
        bar.addWidget(lbl)
        bar.addStretch(1)
        btn_expand = IconToolButton.create(
            "mdi6.arrow-expand-vertical",
            "扩展设备区（临时拉高检视/镜像，不浮动窗口）",
            icon_tone="tool",
        )
        btn_reset = IconToolButton.create(
            "mdi6.restore", "恢复默认上下比例",
            icon_tone="tool",
        )
        btn_expand.clicked.connect(self.expandDeviceRequested)
        btn_reset.clicked.connect(self.resetSplitRequested)
        bar.addWidget(btn_expand)
        bar.addWidget(btn_reset)
        init_panel_style(self, "auxiliary_toolbar")
        self._icon_buttons = (btn_expand, btn_reset)

    def apply_theme(self, theme: str) -> None:
        from ...theme import apply_panel_theme
        from .icon_tool_button import IconToolButton

        apply_panel_theme(self, "auxiliary_toolbar", theme)
        for btn in self._icon_buttons:
            IconToolButton.apply_theme(btn, theme)
