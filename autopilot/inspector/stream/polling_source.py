"""轮询帧源：定时调用截图回调 → QImage。全平台兜底（零额外依赖，低帧率）。"""

from __future__ import annotations

from typing import Callable

from .base import ScreenSource


class PollingScreenSource(ScreenSource):
    def __init__(self, grab: Callable[[], bytes], fps: float = 3.0, parent=None) -> None:
        super().__init__(parent)
        self._grab = grab                       # () -> png bytes（如 driver.get_screenshot_as_png）
        self._interval_ms = int(1000 / max(0.5, fps))

    def run(self) -> None:
        from PyQt6.QtGui import QImage
        while not self._stop:
            # noinspection PyBroadException
            try:
                png = self._grab()
            except Exception as e:  # noqa: BLE001
                # noinspection PyUnresolvedReferences
                self.failed.emit(f"截图轮询失败: {e}")
                return
            if png:
                img = QImage.fromData(png)
                if not img.isNull():
                    # noinspection PyUnresolvedReferences
                    self.frame.emit(img)
            self.msleep(self._interval_ms)
