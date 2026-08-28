"""帧源工厂：按平台 + 可用性选具体 ScreenSource，对调用方屏蔽差异（解耦核心）。

opts 字段（按需提供）：
  avf_capture/avf_helper —— iOS Mac 原生 AVFoundation 高帧采集（与 WDA 控制正交）
  mjpeg_url: str   —— iOS WDA 9100 / Android Appium mjpeg 的流地址
  grab: callable   —— () -> png bytes，轮询兜底用（如 driver.get_screenshot_as_png）
  serial: str      —— Android 设备序列号（scrcpy 用）
返回 ScreenSource 实例或 None（无任何可用源）。
"""

from __future__ import annotations

from typing import Optional

from .base import ScreenSource


def _ios_source(opts: dict, grab) -> Optional[ScreenSource]:
    """iOS 画面：AVFoundation 原生（Mac 高帧）→ MJPEG → 轮询。"""
    if opts.get("avf_capture"):
        from .avf_source import AvfScreenSource
        helper = opts.get("avf_helper") or ""
        if helper:
            return AvfScreenSource(
                helper,
                unique_id=opts.get("avf_unique_id", ""),
                bitrate=opts.get("avf_bitrate", 12_000_000),
                max_width=opts.get("avf_max_width", 0),
                fps=opts.get("avf_fps", 60),
                fallback_grab=grab,
            )
    mjpeg_url = opts.get("mjpeg_url")
    if mjpeg_url:
        from .mjpeg_source import MjpegScreenSource
        return MjpegScreenSource(mjpeg_url, fallback_grab=grab)
    if grab:
        from .polling_source import PollingScreenSource
        return PollingScreenSource(grab)
    return None


def make_source(platform: str, opts: dict) -> Optional[ScreenSource]:
    plat = (platform or "android").lower()
    mjpeg_url = opts.get("mjpeg_url")
    grab = opts.get("grab")

    if plat.startswith("ios"):
        return _ios_source(opts, grab)

    if plat.startswith("android"):
        # 优先 scrcpy(H.264 高帧)，资源/依赖缺失再回退
        from .scrcpy_source import ScrcpyScreenSource
        if ScrcpyScreenSource.available():
            return ScrcpyScreenSource(serial=opts.get("serial", ""),
                                      max_width=opts.get("max_width", 0))
        if mjpeg_url:
            from .mjpeg_source import MjpegScreenSource
            return MjpegScreenSource(mjpeg_url, fallback_grab=grab)
        if grab:
            from .polling_source import PollingScreenSource
            return PollingScreenSource(grab)
        return None

    if grab:
        from .polling_source import PollingScreenSource
        return PollingScreenSource(grab)
    return None


def describe_source(platform: str, opts: dict) -> str:
    """返回将选用的源类型说明（不实例化，用于 UI 提示/测试）。"""
    plat = (platform or "android").lower()
    if plat.startswith("android"):
        from .scrcpy_source import ScrcpyScreenSource
        if ScrcpyScreenSource.available():
            return "scrcpy"
    if plat.startswith("ios"):
        if opts.get("avf_capture") and opts.get("avf_helper"):
            return "avf" + ("+polling-fallback" if opts.get("grab") else "")
        if opts.get("mjpeg_url"):
            return "mjpeg" + ("+polling-fallback" if opts.get("grab") else "")
        if opts.get("grab"):
            return "polling"
        return "none"
    if opts.get("mjpeg_url"):
        return "mjpeg" + ("+polling-fallback" if opts.get("grab") else "")
    if opts.get("grab"):
        return "polling"
    return "none"
