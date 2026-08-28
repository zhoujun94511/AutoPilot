"""离屏 Qt 测试共用 QApplication（含 macOS 字体配置，避免 Sans Serif 警告）。"""

from __future__ import annotations

_APP = None


def get_qt_app():
    """返回进程级 QApplication 单例，首次创建时配置平台 UI 字体。"""
    global _APP
    if _APP is not None:
        return _APP
    from PyQt6.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    from autopilot.ui.branding import configure_app_font

    configure_app_font(_APP)
    return _APP
