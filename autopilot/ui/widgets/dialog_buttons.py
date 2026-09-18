"""对话框底部按钮条：次要 / 可选中间操作 / 主操作（含危险态）。

其它对话框可直接挂本组件，避免再走系统 QMessageBox 的细边框按钮。
约定：主按钮在最右（中文桌面习惯）；危险操作默认焦点落在取消。
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from ..theme import apply_panel_theme, init_panel_style, resolve_theme


class DialogButtonBar(QWidget):
    """右对齐按钮条。``extra_text`` 非空时在取消与主按钮之间再放一颗次要按钮。"""

    accepted = pyqtSignal()
    rejected = pyqtSignal()
    extraClicked = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        primary_text: str = "确定",
        secondary_text: str = "取消",
        extra_text: str = "",
        danger: bool = False,
        default: str = "primary",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dialog_button_bar")
        self._theme = "light"
        self._danger = bool(danger)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addStretch(1)

        self.secondary = self._make_button(secondary_text, "dialog_btn_secondary")
        # noinspection PyUnresolvedReferences
        self.secondary.clicked.connect(self.rejected.emit)
        lay.addWidget(self.secondary)

        self.extra: QPushButton | None = None
        extra = (extra_text or "").strip()
        if extra:
            self.extra = self._make_button(extra, "dialog_btn_secondary")
            # noinspection PyUnresolvedReferences
            self.extra.clicked.connect(self.extraClicked.emit)
            lay.addWidget(self.extra)

        primary_name = "dialog_btn_danger" if self._danger else "dialog_btn_primary"
        self.primary = self._make_button(primary_text, primary_name)
        # noinspection PyUnresolvedReferences
        self.primary.clicked.connect(self.accepted.emit)
        lay.addWidget(self.primary)

        self._apply_default(default if default in ("primary", "secondary", "extra") else "primary")
        self._theme = init_panel_style(self, "dialog_button_bar")

    @staticmethod
    def _make_button(text: str, object_name: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName(object_name)
        btn.setAutoDefault(False)
        btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        return btn

    def _apply_default(self, default: str) -> None:
        self.primary.setDefault(default == "primary")
        self.secondary.setDefault(default == "secondary")
        if self.extra is not None:
            self.extra.setDefault(default == "extra")

    def apply_theme(self, theme: str | None = None) -> None:
        self._theme = apply_panel_theme(self, "dialog_button_bar", resolve_theme(theme))
