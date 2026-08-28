"""scrcpy 帧源（Android H.264，高帧低延迟）。

复用「scrcpy server 视频 socket + PyAV 解 H.264 → 帧」的采集解码核心（见 _scrcpy_core，
不含音频/控制/WebRTC），解出的 RGB 帧转 QImage 喂给 Inspector。属可选组件：
  - 需要可选依赖 `av`(PyAV/ffmpeg) + `adbutils` 与 scrcpy-server 资源(resources/re_scrcpy/)；
  - available() 任一缺失即 False → 工厂自动回退到 MJPEG / 轮询源。
与框架解耦：对外只是又一个 ScreenSource。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QImage

from .base import ScreenSource
from . import _scrcpy_core as core

# scrcpy-server 资源目录（与 re_adb/re_go_ios 同处仓库根 resources/，按需放置）
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVER_DIR = _REPO_ROOT / "resources" / "re_scrcpy"


def _server_binary():
    if _SERVER_DIR.exists():
        for name in ("scrcpy-server", "scrcpy-server.jar"):
            p = _SERVER_DIR / name
            if p.exists():
                return p
    return None


class ScrcpyScreenSource(ScreenSource):
    def __init__(self, serial: str = "", max_width: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.serial = serial
        self.max_width = max_width
        self._core = None

    @staticmethod
    def available() -> bool:
        """需 PyAV + adbutils + scrcpy-server 资源同时具备。"""
        return core.deps_ok() and _server_binary() is not None

    def _ensure_core(self):
        """构造 ScrcpyCore（仅对象、无 I/O）。在启动线程前调用，使 control_sink() 立即可用，
        消除「start() 后线程里才建 core」导致 control_sink() 取到 None 的竞态。"""
        if self._core is None and self.available():
            jar = _server_binary()
            c = core.ScrcpyCore(str(jar), serial=self.serial, max_width=self.max_width)
            c.on_frame = self._emit_frame
            c.on_error = self._emit_error
            self._core = c
        return self._core

    def start(self, *args, **kwargs) -> None:   # QThread.start 重写：先建 core 再起线程
        self._ensure_core()
        super().start(*args, **kwargs)

    def run(self) -> None:
        c = self._ensure_core()
        if c is None:
            # noinspection PyUnresolvedReferences
            self.failed.emit(
                "scrcpy 源不可用：需安装可选依赖 av(PyAV)+adbutils 且在 resources/re_scrcpy/ "
                "放置 scrcpy-server。已自动回退 MJPEG/轮询。")
            return
        # noinspection PyBroadException
        try:
            if not c.start():
                return
            # start() 已起后台解码线程；本 QThread 在此驻留直到 stop()
            while not self._stop and c.alive:
                self.msleep(50)
        except Exception as e:  # noqa: BLE001
            # noinspection PyUnresolvedReferences
            self.failed.emit(f"scrcpy 启动失败：{e}；已回退。")
        finally:
            # noinspection PyBroadException
            try:
                c.stop()
            except Exception:
                pass

    def control_sink(self):
        """返回该 scrcpy 会话的控制汇（控制 socket 未就绪时其方法自动回退 adb shell input）。"""
        if self._ensure_core() is None:
            return None
        from .control import ScrcpyControlSink
        return ScrcpyControlSink(self._core)

    def _emit_frame(self, rgb: bytes, w: int, h: int, stride: int) -> None:
        img = QImage(rgb, w, h, stride, QImage.Format.Format_RGB888).copy()
        # noinspection PyUnresolvedReferences
        self.frame.emit(img)

    def _emit_error(self, msg: str) -> None:
        # noinspection PyUnresolvedReferences
        self.failed.emit(msg)

    def stop(self) -> None:
        if self._core is not None:
            # noinspection PyBroadException
            try:
                self._core.stop()
            except Exception:
                pass
        super().stop()
