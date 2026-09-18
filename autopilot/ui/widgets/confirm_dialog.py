"""应用内确认对话框：小图标 + 正文 + DialogButtonBar。

替代 QMessageBox；按钮语言与编写弹窗一致（描边、4px 圆角），危险操作用红字而非色块。
对外请走 ``autopilot.ui.confirm.confirm`` / ``confirm_tri``，不要直接弹本类。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..actions import qicon
from ..branding import app_icon
from ..theme import apply_dialog_theme, icon_color, resolve_dialog_theme
from .dialog_buttons import DialogButtonBar


class ConfirmDialog(QDialog):
    """两按钮或三按钮确认。``choice`` 为 yes / no / cancel。"""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        text: str,
        *,
        danger: bool = False,
        yes_text: str = "确定",
        no_text: str = "",
        cancel_text: str = "取消",
        default: str = "yes",
        theme: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("confirm_dialog")
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.setMinimumWidth(360)
        self.choice = "cancel"
        self._danger = bool(danger)
        self._theme = "light"

        flags = self.windowFlags()
        flags = flags & ~Qt.WindowType.WindowContextHelpButtonHint
        self.setWindowFlags(flags)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(10)
        self._icon = QLabel()
        self._icon.setObjectName("confirm_icon")
        self._icon.setFixedSize(24, 24)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        body.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)

        self._text = QLabel(text)
        self._text.setObjectName("confirm_text")
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self._text, 1)
        root.addLayout(body)

        default_bar = {"yes": "primary", "no": "extra", "cancel": "secondary"}.get(
            default, "primary"
        )
        if danger and default_bar == "primary" and not (no_text or "").strip():
            default_bar = "secondary"
        self.button_bar = DialogButtonBar(
            self,
            primary_text=yes_text,
            secondary_text=cancel_text,
            extra_text=no_text,
            danger=danger,
            default=default_bar,
        )
        # noinspection PyUnresolvedReferences
        self.button_bar.accepted.connect(lambda: self._finish("yes"))
        # noinspection PyUnresolvedReferences
        self.button_bar.rejected.connect(lambda: self._finish("cancel"))
        # noinspection PyUnresolvedReferences
        self.button_bar.extraClicked.connect(lambda: self._finish("no"))
        root.addWidget(self.button_bar)

        self.apply_theme(theme)

    def apply_theme(self, theme: str | None = None) -> None:
        self._theme = apply_dialog_theme(self, "confirm_dialog", theme)
        self.button_bar.apply_theme(self._theme)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        theme = resolve_dialog_theme(self, self._theme)
        if self._danger:
            name, tone = "mdi6.alert-circle-outline", "warn"
        else:
            name, tone = "mdi6.help-circle-outline", "nav_active"
        ic = qicon(name, color=icon_color(tone, theme))
        if ic is not None:
            self._icon.setPixmap(ic.pixmap(QSize(24, 24)))
            self._icon.show()
        else:
            self._icon.hide()

    def _finish(self, choice: str) -> None:
        self.choice = choice
        if choice == "yes":
            self.accept()
        else:
            self.reject()

    def reject(self) -> None:
        if self.choice not in ("yes", "no"):
            self.choice = "cancel"
        super().reject()
