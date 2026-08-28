"""Web 引擎选择器（Selenium / Playwright；web 工程或检视时显示）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox


class WebEngineSelector(QWidget):
    engineChanged = pyqtSignal(str)

    def __init__(self, initial_engine: str = "selenium", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("status_bar_field")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._label = QLabel("Web 引擎")
        lay.addWidget(self._label)
        self.combo = QComboBox()
        self.combo.setObjectName("web_engine_combo")
        self.combo.addItem("Selenium", "selenium")
        self.combo.addItem("Playwright", "playwright")
        eng = (initial_engine or "selenium").strip().lower()
        if eng not in ("selenium", "playwright"):
            eng = "selenium"
        self.combo.setCurrentIndex(max(0, self.combo.findData(eng)))
        self.combo.setToolTip(
            "Web 执行引擎：Selenium 为默认；Playwright 为可选增强。"
        )
        lay.addWidget(self.combo)
        # noinspection PyUnresolvedReferences
        self.combo.currentIndexChanged.connect(
            # noinspection PyUnresolvedReferences
            lambda _i: self.engineChanged.emit(
                str(self.combo.currentData() or "selenium")
            )
        )

    def set_visible_for_platform(self, platform: str) -> None:
        visible = (platform or "").strip().lower() == "web"
        self._label.setVisible(visible)
        self.combo.setVisible(visible)
