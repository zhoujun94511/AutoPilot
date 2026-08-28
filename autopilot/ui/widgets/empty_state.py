"""空状态组件：居中「图标 + 标题 + 说明」，用于无内容时的占位（检视器/镜像等）。

替代裸 QLabel 文案，统一观感；图标走 qtawesome（按主题取灰度色），缺失时优雅退化为纯文字。
默认作为覆盖层（鼠标透传）；也可作为 QStackedWidget 的整页内容。
compact=True 用于次要栏（如已有快照但未选中控件），缩小图标与字号，避免与主空态抢视线。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ..actions import qicon
from ..theme import init_panel_style, resolve_theme


class EmptyState(QWidget):
    def __init__(
        self,
        icon: str = "mdi6.information-outline",
        parent=None,
        *,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon_name = icon
        self._theme = "light"
        self._compact = bool(compact)
        self._icon_px = 36 if self._compact else 52
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(6 if self._compact else 10)
        lay.setContentsMargins(16, 16, 16, 16)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel()
        self._title.setObjectName(
            "empty_state_title_compact" if self._compact else "empty_state_title")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint = QLabel()
        self._hint.setObjectName(
            "empty_state_hint_compact" if self._compact else "empty_state_hint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        lay.addStretch(1)
        lay.addWidget(self._icon)
        lay.addWidget(self._title)
        lay.addWidget(self._hint)
        lay.addStretch(1)
        init_panel_style(self, "empty_state")
        self.apply_theme(self._theme)

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme

        self._theme = resolve_theme(theme)
        apply_panel_theme(self, "empty_state", self._theme)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        from ..theme import semantic_color

        mid = semantic_color("mid", self._theme)
        ic = qicon(self._icon_name, color=mid)
        if ic is not None:
            self._icon.setPixmap(ic.pixmap(self._icon_px, self._icon_px))
            self._icon.show()
        else:
            self._icon.hide()

    def show_state(self, title: str, hint: str = "", icon: str = "") -> None:
        if icon:
            self._icon_name = icon
        self._title.setText(title)
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))
        self._refresh_icon()
