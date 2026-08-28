"""AVFoundation 原生 iOS 屏幕采集帧源（仅 Mac 高帧镜像）。

启动本地 helper ``ios-avf-capture``（Swift，启用 CoreMediaIO 隐藏采集设备并从
AVFoundation 取 iPhone 屏幕，用 VideoToolbox 硬件 H.264 编码），读取其 stdout 的
H.264 Annex-B 裸流，用 PyAV 解码为 QImage。

协议：magic ``AVFH``（4 字节，仅首次）后是连续的 Annex-B H.264 裸流
（``00 00 00 01`` 起始码分隔的 NAL，SPS/PPS 在每个 IDR 前重发）。

为什么走 H.264 而不是逐帧 JPEG：硬件时域压缩能轻松跑满 60fps，管道每帧带宽从数百 KB
降到 ~10-50KB，观感才能接近 QuickTime（逐帧 JPEG 本质等同 9100 MJPEG，白绕一圈）。

关键：消费的是系统 CoreMediaIO 采集设备（与 QuickTime 同源），不抢占 USB 接口，
因此与 go-ios/WDA 控制通道共存，无需 USB 重置（详见 docs/ios_mirror_qvh_analysis.md）。
"""

from __future__ import annotations

import logging
import os
import select
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .base import ScreenSource

_log = logging.getLogger(__name__)

_MAGIC = b"AVFH"


def _parse_h264_chunk(decoder, chunk: bytes) -> list:
    # noinspection PyPackageRequirements
    from av.error import FFmpegError

    try:
        return list(decoder.parse(chunk))
    except FFmpegError:
        return []


def _decode_h264_packet(decoder, packet) -> list:
    # noinspection PyPackageRequirements
    from av.error import FFmpegError

    try:
        return list(decoder.decode(packet))
    except FFmpegError:
        return []


def _log_dir() -> Path:
    d = Path.home() / ".autopilot" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


class AvfScreenSource(ScreenSource):
    def __init__(
        self,
        helper_path: str,
        unique_id: str = "",
        bitrate: int = 12_000_000,
        max_width: int = 0,
        fps: int = 60,
        fallback_grab: Optional[Callable[[], bytes]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._helper = helper_path
        self._unique_id = (unique_id or "").strip()
        self._bitrate = int(bitrate)
        self._max_width = int(max_width)   # 解码后下采样上限（0=原生），控制解码/GUI 上传成本
        self._fps = int(fps)
        self._fallback_grab = fallback_grab
        self._proc: Optional[subprocess.Popen] = None
        self._log_file = None

    @staticmethod
    def available() -> bool:
        from ...mobile.ios_mirror import avf_capture_available
        return avf_capture_available()

    def stop(self) -> None:
        self._stop = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            # noinspection PyBroadException
            try:
                proc.terminate()
            except Exception:
                pass
        self.wait(5000)
        if proc is not None and proc.poll() is None:
            # noinspection PyBroadException
            try:
                proc.kill()
            except Exception:
                pass

    def run(self) -> None:
        if not self._helper or not os.path.isfile(self._helper):
            self._fail("未找到 ios-avf-capture helper（tools/ios_avf_capture/build.sh 构建）")
            return
        # noinspection PyBroadException
        try:
            self._run_capture()
        except Exception as e:  # noqa: BLE001
            if not self._stop:
                self._fail(str(e))
        finally:
            self._cleanup_proc()

    def _run_capture(self) -> None:
        try:
            # noinspection PyPackageRequirements
            import av  # FFmpeg 绑定；macOS 上可用 VideoToolbox 硬解
        except ImportError as e:  # pragma: no cover - 环境缺依赖
            raise RuntimeError(f"缺少 PyAV，无法解码 H.264 视频流：{e}") from e

        args = [
            self._helper,
            "--bitrate", str(self._bitrate),
            "--fps", str(self._fps),
        ]
        if self._unique_id:
            args += ["--unique-id", self._unique_id]

        log_path = _log_dir() / "avf-capture.log"
        self._log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        # bufsize=0：裸流低延迟——read() 返回当前可用字节即喂解码器，不等凑满。
        self._proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=self._log_file, bufsize=0,
        )
        out = self._proc.stdout
        assert out is not None

        magic = self._read_exact(out, 4)
        if magic != _MAGIC:
            # helper 可能因权限/无设备而提前退出，读 stderr 尾部给出可诊断原因
            raise RuntimeError(self._exit_reason(log_path) or "AVFoundation 采集未输出帧")
        _log.info("AVFoundation 采集已连接 helper=%s（H.264）", os.path.basename(self._helper))

        decoder = av.CodecContext.create("h264", "r")
        got_frame = False
        _read_timeout = 5.0   # 避免管道无数据时 read 永久阻塞，导致无法 stop/重启
        while not self._stop:
            ready: list = []
            try:
                ready, _, _ = select.select([out], [], [], _read_timeout)
            except (ValueError, OSError):
                break
            if self._stop:
                break
            if not ready:
                proc = self._proc
                if proc is not None and proc.poll() is not None:
                    break
                continue
            chunk = out.read(65536)
            if not chunk:
                break
            chunk_packets = _parse_h264_chunk(decoder, chunk)
            if not chunk_packets:
                continue
            for packet in chunk_packets:
                if self._stop:
                    break
                frame_list = _decode_h264_packet(decoder, packet)
                if not frame_list:
                    continue
                for frame in frame_list:
                    if self._stop:
                        break
                    img = self._frame_to_qimage(frame)
                    if img is None:
                        continue
                    if not got_frame:
                        got_frame = True
                        _log.info("AVFoundation 首帧 %sx%s", img.width(), img.height())
                    # noinspection PyUnresolvedReferences
                    self.frame.emit(img)

        if not self._stop:
            msg = self._exit_reason(log_path) or (
                "AVFoundation 采集中断（无首帧）" if not got_frame else "AVFoundation 采集中断")
            raise RuntimeError(msg)

    def _frame_to_qimage(self, frame):
        """PyAV VideoFrame → QImage(RGB888)。按 max_width 下采样以控解码/GUI 上传成本。"""
        from PyQt6.QtGui import QImage

        tw, th = frame.width, frame.height
        if 0 < self._max_width < tw:
            th = int(round(th * self._max_width / tw))
            th -= th % 2                 # swscale 目标高度取偶，避免色度对齐问题
            tw = self._max_width
            rgb = frame.reformat(width=tw, height=th, format="rgb24")
        else:
            rgb = frame.reformat(format="rgb24")
        arr = rgb.to_ndarray()           # (H, W, 3) uint8，行连续
        h, w, _ = arr.shape
        # QImage 不拷贝底层数据；.copy() 让 QImage 拥有内存后再跨线程 emit（否则悬垂）
        return QImage(arr.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888).copy()

    def _read_exact(self, stream, n: int) -> Optional[bytes]:
        """从管道读满 n 字节；进程退出/停止返回 None 或不足。"""
        buf = bytearray()
        while len(buf) < n:
            if self._stop:
                return None
            chunk = stream.read(n - len(buf))
            if not chunk:
                return bytes(buf) if buf else None
            buf.extend(chunk)
        return bytes(buf)

    @staticmethod
    def _exit_reason(log_path: Path) -> str:
        # noinspection PyBroadException
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            rows = [r for r in text.splitlines() if r.strip()]
            tail = rows[-6:] if rows else []
            for r in reversed(tail):
                if "ERROR" in r or "permission" in r.lower():
                    return r.strip()
            return "；".join(tail[-2:]) if tail else ""
        except Exception:
            return ""

    def _cleanup_proc(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            # noinspection PyBroadException
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                # noinspection PyBroadException
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._log_file is not None:
            # noinspection PyBroadException
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self._proc = None

    def _fail(self, reason: str) -> None:
        if self._stop:
            _log.debug("AVFoundation 已停止，忽略中断：%s", (reason or "")[:120])
            return
        _log.error("AVFoundation 帧源失败：%s", reason)
        # noinspection PyUnresolvedReferences
        self.failed.emit(reason)
