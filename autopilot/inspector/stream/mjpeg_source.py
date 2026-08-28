"""MJPEG 帧源：读 HTTP multipart MJPEG 流，按 JPEG 边界切帧 → QImage。

适用：iOS WDA 9100 端口的屏幕 MJPEG、Android Appium uiautomator2 的 mjpegServer。
零额外依赖（httpx 已有，JPEG 由 Qt 原生解码）。
"""

from __future__ import annotations

from .base import ScreenSource

# JPEG 起止标记
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"


def split_jpegs(buf: bytes) -> tuple:
    """从字节缓冲里切出完整 JPEG 帧。返回 (帧列表, 剩余缓冲)。纯函数、可测。"""
    frames = []
    while True:
        s = buf.find(_SOI)
        if s < 0:
            return frames, buf[-1:] if buf[-1:] == b"\xff" else b""
        e = buf.find(_EOI, s + 2)
        if e < 0:
            return frames, buf[s:]      # 半帧，保留等后续字节
        frames.append(buf[s:e + 2])
        buf = buf[e + 2:]


class MjpegScreenSource(ScreenSource):
    def __init__(self, url: str, fallback_grab=None, fps: float = 3.0, parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self._fallback_grab = fallback_grab
        self._interval_ms = int(1000 / max(0.5, fps))

    def run(self) -> None:
        # noinspection PyUnresolvedReferences
        import httpx
        from PyQt6.QtGui import QImage
        buf = b""
        # read 超时：WDA MJPEG 长时间无字节时 iter_bytes 会永久阻塞；超时抛错走 failed/回退
        timeout = httpx.Timeout(connect=15.0, read=10.0, write=10.0, pool=10.0)
        # noinspection PyBroadException
        try:
            with httpx.stream("GET", self.url, timeout=timeout) as resp:
                for chunk in resp.iter_bytes():
                    if self._stop:
                        break
                    buf += chunk
                    frames, buf = split_jpegs(buf)
                    if frames:
                        jpg = frames[-1]          # 只渲染最新帧，避免滑动时积压延迟
                        if self._stop:
                            break
                        img = QImage.fromData(jpg)
                        if not img.isNull():
                            # noinspection PyUnresolvedReferences
                            self.frame.emit(img)
        except Exception as e:  # noqa: BLE001
            if self._stop:
                return
            if self._fallback_grab is not None:
                # noinspection PyUnresolvedReferences
                self.mode_changed.emit("polling-fallback")
                self._run_polling_fallback()
                return
            # noinspection PyUnresolvedReferences
            self.failed.emit(f"MJPEG 流中断: {e}")

    def _run_polling_fallback(self) -> None:
        """MJPEG 断流后回退截屏轮询（低帧率但可继续镜像）。"""
        from PyQt6.QtGui import QImage
        while not self._stop:
            # noinspection PyBroadException
            try:
                png = self._fallback_grab()
            except Exception as e:  # noqa: BLE001
                if not self._stop:
                    # noinspection PyUnresolvedReferences
                    self.failed.emit(f"MJPEG 断流且截图回退失败: {e}")
                return
            if png:
                img = QImage.fromData(png)
                if not img.isNull():
                    # noinspection PyUnresolvedReferences
                    self.frame.emit(img)
            self.msleep(self._interval_ms)
