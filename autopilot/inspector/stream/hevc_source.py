"""Windows / Linux 上的 iOS 27 HEVC 镜像。

消费 ``IosHevcStream`` 的 Annex-B，用 PyAV 解成 QImage。macOS 仍走 AVFoundation。
开流失败由调用方回退 WDA MJPEG。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from .base import ScreenSource

_log = logging.getLogger(__name__)


def _decode_packets(decoder, chunk: bytes) -> list:
    # noinspection PyPackageRequirements
    from av.error import FFmpegError

    frames = []
    try:
        packets = list(decoder.parse(chunk))
    except FFmpegError:
        return frames
    for packet in packets:
        try:
            frames.extend(decoder.decode(packet))
        except FFmpegError:
            continue
    return frames


class HevcScreenSource(ScreenSource):
    def __init__(
        self,
        udid: str,
        max_width: int = 1080,
        fallback_grab: Optional[Callable[[], bytes]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._udid = (udid or "").strip()
        self._max_width = int(max_width or 0)
        self._fallback_grab = fallback_grab
        self._stream = None

    def stop(self) -> None:
        self._stop = True
        stream = self._stream
        if stream is not None:
            # noinspection PyBroadException
            try:
                stream.stop()
            except Exception:  # noqa: BLE001
                pass
        self.wait(5000)

    def run(self) -> None:
        if not self._udid:
            self._fail("缺少设备 UDID，无法打开 HEVC")
            return
        try:
            self._run_capture()
        except Exception as exc:  # noqa: BLE001
            if not self._stop:
                self._fail(str(exc))
        finally:
            stream = self._stream
            self._stream = None
            if stream is not None:
                # noinspection PyBroadException
                try:
                    stream.stop()
                except Exception:  # noqa: BLE001
                    pass

    def _run_capture(self) -> None:
        try:
            # noinspection PyPackageRequirements
            import av
        except ImportError as exc:
            raise RuntimeError(f"缺少 PyAV，无法解码 HEVC：{exc}") from exc
        from ...mobile.ios_hevc import IosHevcStream, annexb_access_unit

        stream = IosHevcStream(self._udid)
        self._stream = stream
        stream.start()
        decoder = av.CodecContext.create("hevc", "r")
        got_frame = False
        while not self._stop:
            unit = stream.read(0.5)
            if unit is None:
                if not stream.health():
                    break
                continue
            chunk = annexb_access_unit(unit)
            if not chunk:
                continue
            for frame in _decode_packets(decoder, chunk):
                if self._stop:
                    break
                img = self._frame_to_qimage(frame)
                if img is None:
                    continue
                if not got_frame:
                    got_frame = True
                    _log.info("iOS HEVC 首帧 %sx%s", img.width(), img.height())
                self.frame.emit(img)
        if not self._stop:
            raise RuntimeError(
                "HEVC 采集中断（无首帧）" if not got_frame else "HEVC 采集中断"
            )

    def _frame_to_qimage(self, frame):
        from PyQt6.QtGui import QImage

        tw, th = frame.width, frame.height
        if 0 < self._max_width < tw:
            th = int(round(th * self._max_width / tw))
            th -= th % 2
            tw = self._max_width
            rgb = frame.reformat(width=tw, height=th, format="rgb24")
        else:
            rgb = frame.reformat(format="rgb24")
        arr = rgb.to_ndarray()
        h, w, _ = arr.shape
        return QImage(arr.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888).copy()

    def _fail(self, reason: str) -> None:
        self.failed.emit(reason or "HEVC 采集失败")
