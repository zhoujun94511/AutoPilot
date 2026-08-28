"""屏幕帧源抽象基类：统一 start/stop + frame(QImage)/failed(str) 信号。

各具体源(MJPEG / scrcpy / 轮询)继承并实现 run()，在后台线程产帧；
Inspector 只依赖此抽象，不关心底层取流方式 —— 帧源与渲染/检视完全解耦。
"""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class ScreenSource(QThread):
    frame = pyqtSignal(object)     # 一帧 QImage
    failed = pyqtSignal(str)       # 取流失败原因
    mode_changed = pyqtSignal(str) # 实际帧源切换（如 mjpeg → 截图轮询）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        self.wait(3000)

    # 子类实现 run()：循环产帧，期间检查 self._stop
    def run(self) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError
