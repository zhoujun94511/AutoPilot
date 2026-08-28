"""iOS 镜像 MJPEG 9100 画面 opts 组装（WDA + go-ios usbmux 转发）。

高帧路径（Mac AVFoundation 原生采集）由 ``inspector/stream/avf_source`` 负责；
本模块只负责 MJPEG 9100 回退/显式模式的 opts 组装（与检视/执行共用 WDA 隧道）。
"""

from __future__ import annotations

from .ios_bootstrap import (
    DEFAULT_MJPEG_PORT,
    ensure_mjpeg_ready,
    mjpeg_alive,
)


def build_mjpeg_opts(
    udid: str,
    mgr,
    *,
    include_grab: bool = True,
) -> dict:
    """WDA 就绪后的 MJPEG 画面 opts（与检视/执行共用 go-ios 隧道）。"""
    mjpeg_port = (getattr(mgr, "mjpeg_port", None) if mgr is not None else None) or DEFAULT_MJPEG_PORT
    prep = getattr(mgr, "_ios_prep", None) if mgr is not None else None
    ensure_mjpeg_ready(udid, mjpeg_port, prep=prep)
    opts: dict = {}
    if mjpeg_alive(mjpeg_port):
        opts["mjpeg_url"] = f"http://127.0.0.1:{mjpeg_port}"
    if include_grab and mgr is not None:
        # noinspection PyBroadException
        try:
            opts["grab"] = mgr.driver().get_screenshot_as_png
        except Exception:
            pass
    return opts
