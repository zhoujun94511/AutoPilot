"""运行进度条：单用例不确定进度 / 批量用例计数。"""

from __future__ import annotations

from PyQt6.QtWidgets import QProgressBar


class RunProgressBar(QProgressBar):
    """状态栏运行进度；由 RunMixin 在 worker 生命周期内驱动。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("run_progress_bar")
        self.setMaximumWidth(160)
        self.setTextVisible(True)
        self.setVisible(False)
        self._total = 0
        self._done = 0

    def begin(self, case_count: int) -> None:
        self._total = max(0, case_count)
        self._done = 0
        if self._total > 1:
            self.setRange(0, self._total)
            self.setValue(0)
            self.setFormat("用例 %v/%m")
        else:
            self.setRange(0, 0)
            self.setFormat("执行中…")
        self.setVisible(True)

    def advance_case(self) -> None:
        if self._total <= 1:
            return
        self._done = min(self._done + 1, self._total)
        self.setValue(self._done)

    def end(self) -> None:
        self.setVisible(False)
        self._total = 0
        self._done = 0
