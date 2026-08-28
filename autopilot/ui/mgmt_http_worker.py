"""管理台 HTTP 后台任务：避免 zip/上传/登录阻塞 IDE UI 线程。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal


class MgmtHttpWorker(QThread):
    """在后台执行 ``fn()``，经 ``done`` 回传结果或异常。"""

    done = pyqtSignal(object)

    def __init__(self, fn: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            # noinspection PyUnresolvedReferences
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 — 需带回主线程展示
            # noinspection PyUnresolvedReferences
            self.done.emit(exc)
