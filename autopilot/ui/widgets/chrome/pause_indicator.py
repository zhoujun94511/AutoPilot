"""状态栏「执行已暂停」指示。"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from ...actions import qicon


class PauseIndicator(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("pause_indicator")
        self.setToolTip("执行已暂停，点击工具栏「继续」恢复")
        self._theme = "light"
        self.apply_theme(self._theme)
        self.setVisible(False)

    def apply_theme(self, theme: str) -> None:
        from ...theme import icon_color, resolve_theme

        self._theme = resolve_theme(theme)
        ic = qicon("mdi6.pause-circle", color=icon_color("warn", self._theme))
        if ic is not None:
            self.setPixmap(ic.pixmap(16, 16))

    def set_paused(self, on: bool) -> None:
        self.setVisible(on)
