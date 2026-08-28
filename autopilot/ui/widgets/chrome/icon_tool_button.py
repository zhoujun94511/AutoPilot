"""图标工具按钮工厂（qtawesome → Qt 标准图标 → 可读短文案）。"""

from __future__ import annotations

from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QStyle, QToolButton

from ...actions import qicon

_PROP_ICON = "_ap_icon"
_PROP_TONE = "_ap_icon_tone"

# qtawesome 名 → Qt 标准图标（无 mdi 字体时仍显示可识别图形）
_STD_ICON_MAP: dict[str, QStyle.StandardPixmap] = {
    "mdi6.plus": QStyle.StandardPixmap.SP_FileDialogNewFolder,
    "mdi6.folder-plus-outline": QStyle.StandardPixmap.SP_FileDialogNewFolder,
    "mdi6.refresh": QStyle.StandardPixmap.SP_BrowserReload,
    "mdi6.collapse-all-outline": QStyle.StandardPixmap.SP_ArrowUp,
    "mdi6.play-circle-outline": QStyle.StandardPixmap.SP_MediaPlay,
    "mdi6.checkbox-multiple-marked-outline": QStyle.StandardPixmap.SP_DialogApplyButton,
    "mdi6.checkbox-blank-outline": QStyle.StandardPixmap.SP_DialogResetButton,
    "mdi6.folder-outline": QStyle.StandardPixmap.SP_DirIcon,
    "mdi6.magnify": QStyle.StandardPixmap.SP_FileDialogContentsView,
    "mdi6.content-save": QStyle.StandardPixmap.SP_DialogSaveButton,
    "mdi6.restore": QStyle.StandardPixmap.SP_BrowserStop,
    "mdi6.arrow-expand-vertical": QStyle.StandardPixmap.SP_ArrowDown,
}


def _label_from_tip(tip: str) -> str:
    """从 tooltip 取可见短标签（首句、去省略号）。"""
    s = (tip or "").strip().split("（")[0].split("(")[0].split("…")[0].strip()
    if not s:
        return "…"
    return s[:4] if len(s) > 4 else s


def _resolve_icon(icon: str, color: str = "") -> QIcon | None:
    ic = qicon(icon, color=color) if color else qicon(icon)
    if ic is not None and not ic.isNull():
        return ic
    sp = _STD_ICON_MAP.get(icon)
    if sp is None:
        return None
    app = cast(QApplication, QApplication.instance())
    if app is None:
        return None
    std = app.style().standardIcon(sp)
    return std if not std.isNull() else None


class IconToolButton:
    """统一创建工程区/导航区图标按钮；图标色走 theme.icon_color。"""

    @staticmethod
    def create(
        icon: str,
        tip: str,
        *,
        label: str = "",
        object_name: str = "",
        text: str = "",
        text_beside_icon: bool = False,
        icon_tone: str = "tool",
        parent=None,
    ) -> QToolButton:
        btn = QToolButton(parent)
        if object_name:
            btn.setObjectName(object_name)
        btn.setProperty(_PROP_ICON, icon)
        btn.setProperty(_PROP_TONE, icon_tone)
        visible = (label or _label_from_tip(tip)).strip()
        IconToolButton.apply_theme(btn, None, icon_tone)
        ic = btn.icon()
        if not ic.isNull():
            if text:
                btn.setText(text)
                if text_beside_icon:
                    btn.setToolButtonStyle(
                        Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        else:
            btn.setText(text or visible)
            if text_beside_icon and text:
                btn.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        return btn

    @staticmethod
    def apply_theme(
        btn: QToolButton,
        theme: str | None = None,
        icon_tone: str | None = None,
    ) -> None:
        """按主题刷新按钮图标色（切换深浅色后须调用）。"""
        icon = btn.property(_PROP_ICON)
        if not icon:
            return
        tone = icon_tone or btn.property(_PROP_TONE) or "tool"
        from ...theme import effective_theme, icon_color

        resolved = effective_theme(theme)
        color = icon_color(tone, resolved)
        ic = _resolve_icon(str(icon), color)
        if ic is not None:
            btn.setIcon(ic)
