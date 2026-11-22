"""自动测试共用的静态 Qt 对话框替身，避免离屏运行等待用户输入。"""

from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def stub_modal_dialogs():
    """提供默认值；测试内部自己的 patch 会覆盖这些外层默认。"""
    try:
        from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
    except (ImportError, ModuleNotFoundError):
        yield
        return

    input_defaults = {
        "getItem": lambda *a, **k: ("通用", True),
        "getText": lambda *a, **k: ("", True),
        "getInt": lambda *a, **k: (0, True),
        "getDouble": lambda *a, **k: (0.0, True),
    }
    message_defaults = {
        "question": lambda *a, **k: QMessageBox.StandardButton.Yes,
        "warning": lambda *a, **k: QMessageBox.StandardButton.Ok,
        "information": lambda *a, **k: QMessageBox.StandardButton.Ok,
        "critical": lambda *a, **k: QMessageBox.StandardButton.Ok,
    }
    file_defaults = {
        "getOpenFileName": lambda *a, **k: ("", ""),
        "getSaveFileName": lambda *a, **k: ("", ""),
        "getExistingDirectory": lambda *a, **k: "",
    }
    patchers = []

    def stop_patchers() -> None:
        while patchers:
            patchers.pop().stop()

    for owner, methods in (
        (QInputDialog, input_defaults), (QMessageBox, message_defaults),
        (QFileDialog, file_defaults),
    ):
        for name, default in methods.items():
            patcher = patch.object(owner, name, staticmethod(default), create=True)
            patcher.start()
            patchers.append(patcher)
    try:
        yield
    except BaseException:
        stop_patchers()
        raise
    stop_patchers()


@contextmanager
def isolate_main_window_startup():
    """窗口构造时不回收宿主真实 iOS 会话；独立的回收逻辑测试不受影响。"""
    from autopilot.ui.main_window import window as main_window

    original = main_window.build_statusbar

    def build_for_test(target):
        with patch("autopilot.mobile.ios_bootstrap.reclaim_stale_local_ios_prep",
                   return_value=([], [])):
            return original(target)

    with patch.object(main_window, "build_statusbar", build_for_test):
        yield
