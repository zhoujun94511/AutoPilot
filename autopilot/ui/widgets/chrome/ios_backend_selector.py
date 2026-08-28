"""iOS 后端模式选择器（仅 iOS 工程显示）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox


class IosBackendSelector(QWidget):
    backendChanged = pyqtSignal(str)

    def __init__(self, initial_mode: str = "auto", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("status_bar_field")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._label = QLabel("iOS 后端")
        lay.addWidget(self._label)
        self.combo = QComboBox()
        self.combo.setObjectName("ios_backend_combo")
        self.combo.addItem("Auto", "auto")
        self.combo.addItem("Appium", "appium")
        self.combo.addItem("WDA-direct", "wda")
        self.combo.setCurrentIndex(max(0, self.combo.findData(initial_mode)))
        self.combo.setToolTip(
            "iOS 连接方式：自动=按本机环境选择；"
            "Appium=经 Appium 服务；直连=直接连 WebDriverAgent。"
        )
        lay.addWidget(self.combo)
        # noinspection PyUnresolvedReferences
        self.combo.currentIndexChanged.connect(
            # noinspection PyUnresolvedReferences
            lambda _i: self.backendChanged.emit(str(self.combo.currentData() or "auto")))

    def set_visible_for_platform(self, platform: str) -> None:
        visible = platform == "ios"
        self._label.setVisible(visible)
        self.combo.setVisible(visible)
