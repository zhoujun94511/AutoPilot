"""失败策略选择器（状态栏左侧）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox

from ....engine import FaultStrategy


class FaultStrategySelector(QWidget):
    strategyChanged = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("status_bar_field")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(QLabel("失败策略"))
        self.combo = QComboBox()
        self.combo.setObjectName("fault_strategy_combo")
        self.combo.addItem("失败继续", FaultStrategy.CONTINUE)
        self.combo.addItem("失败即停", FaultStrategy.STOP)
        lay.addWidget(self.combo)
        # noinspection PyUnresolvedReferences
        self.combo.currentIndexChanged.connect(
            # noinspection PyUnresolvedReferences
            lambda _i: self.strategyChanged.emit(self.combo.currentData()))

    def current_strategy(self) -> FaultStrategy:
        return self.combo.currentData()
