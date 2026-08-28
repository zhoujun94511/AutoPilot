"""iOS 实时镜像视频源策略（可插拔、与 WDA/Appium 控制解耦）。

高帧画面（仅 Mac）：
  - **AVFoundation 原生采集**（``ios-avf-capture`` + CoreMediaIO）：消费系统采集
    设备（与 QuickTime 同源），与 go-ios/WDA 控制共存，不抢占 USB 接口。
  - Win/Linux：无高帧路径，走 WDA MJPEG 9100 / 截图轮询。

历史备注：早期尝试过 QVH（ws-qvh / libusb 抓 QuickTime USB H.264），但现代 macOS 的
CoreMediaIO DriverKit 扩展会独占 QuickTime 采集接口，libusb 无法 claim
（``LIBUSB_ERROR_OTHER``），该路线已废弃。详见 docs/ios_mirror_qvh_analysis.md。

边界：
  - 默认 ``auto``：Mac → AVFoundation 高帧；``mjpeg`` 显式强制 9100 画面。
  - 高帧失败/断流：先重启采集源；仍失败且允许回退时 → WDA MJPEG 9100（生产默认）。
  - 调试：设 ``IOS_MIRROR_STRICT=1`` 关闭 →MJPEG 自动回退，避免掩盖缺陷。
  - 首帧到达后再启 WDA/Appium 控制（ws-scrcpy 顺序）。

环境变量（优先于设置项）：
  IOS_MIRROR_SOURCE=auto|mjpeg
  IOS_MIRROR_STRICT=1        # 调试：禁用高帧→MJPEG 自动回退
  IOS_AVF_BIN=/path/to/ios-avf-capture

构建与排障详见 docs/setup/ios_avf_capture.md。
"""

from __future__ import annotations

import os
import shutil

from ..keywords.mobile.platform import host_os

MIRROR_MJPEG = "mjpeg"
MIRROR_AUTO = "auto"
_VALID_MIRROR_SOURCES = {MIRROR_MJPEG, MIRROR_AUTO}


def normalize_mirror_source(mode: str = "") -> str:
    value = (mode or "").strip().lower()
    if not value:
        return MIRROR_AUTO
    # 兼容历史取值 "qvh"：高帧意图，等价 auto（Mac 走 AVFoundation）
    if value == "qvh":
        return MIRROR_AUTO
    return value if value in _VALID_MIRROR_SOURCES else MIRROR_AUTO


def mirror_source_from_env() -> str:
    raw = os.getenv("IOS_MIRROR_SOURCE", "").strip().lower()
    return normalize_mirror_source(raw) if raw else ""


def resolve_mirror_source(mode: str = "", host: str = "") -> str:
    """解析镜像视频源意图（不含 helper 是否装好的探测）。

    auto：Mac → 优先 AVFoundation 高帧；Win/Linux → 等价 mjpeg（无高帧路径）。
    """
    env_mode = mirror_source_from_env()
    if env_mode:
        chosen = env_mode
    else:
        chosen = normalize_mirror_source(mode)
    host = host or host_os()
    if chosen == MIRROR_AUTO and host != "mac":
        return MIRROR_MJPEG
    return chosen


def avf_helper_path() -> str:
    """原生 AVFoundation 采集 helper（ios-avf-capture）路径。

    优先级：IOS_AVF_BIN 覆盖 → 仓库内构建产物 → PATH。
    """
    override = (os.getenv("IOS_AVF_BIN") or "").strip()
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    from pathlib import Path
    built = Path(__file__).resolve().parents[2] / "tools" / "ios_avf_capture" / "ios-avf-capture"
    if built.is_file() and os.access(built, os.X_OK):
        return str(built)
    return shutil.which("ios-avf-capture") or ""


def avf_capture_available(host: str = "") -> bool:
    """AVFoundation 原生采集是否可用：仅 Mac + helper 已构建。

    帧走 H.264 硬件编码（Swift VTCompressionSession）+ PyAV 解码，不依赖 WDA MJPEG。
    """
    if (host or host_os()) != "mac":
        return False
    return bool(avf_helper_path())


def build_avf_opts(udid: str = "", *, grab=None) -> dict:
    """组装 AVFoundation 高帧镜像 opts（``_mirror_session`` 与断流重启共用）。

    ``avf_unique_id`` 必须为设备 UDID，否则可能误选 Continuity Camera。
    编码参数见 env：``IOS_MIRROR_MAX_WIDTH`` / ``IOS_MIRROR_BITRATE`` / ``IOS_MIRROR_FPS``。
    """
    opts: dict = {
        "avf_capture": True,
        "avf_helper": avf_helper_path(),
        "avf_unique_id": (udid or "").strip(),
    }
    if grab is not None:
        opts["grab"] = grab
    _mw = os.getenv("IOS_MIRROR_MAX_WIDTH", "").strip()
    try:
        opts["avf_max_width"] = max(0, int(_mw)) if _mw else 1080
    except ValueError:
        opts["avf_max_width"] = 1080
    _br = os.getenv("IOS_MIRROR_BITRATE", "").strip()
    if _br:
        try:
            opts["avf_bitrate"] = max(1_000_000, int(_br))
        except ValueError:
            pass
    _fps = os.getenv("IOS_MIRROR_FPS", "").strip()
    if _fps:
        try:
            opts["avf_fps"] = min(60, max(15, int(_fps)))
        except ValueError:
            pass
    return opts


def wants_highfps_video(mode: str = "", host: str = "") -> bool:
    """auto 表示"要高帧画面"（Mac → AVFoundation），mjpeg 则否。"""
    return resolve_mirror_source(mode, host=host) == MIRROR_AUTO


def can_try_avf_mirror(mode: str = "", host: str = "") -> bool:
    """Mac 上高帧意图 + AVFoundation helper 就绪 → 走原生采集。"""
    return wants_highfps_video(mode, host=host) and avf_capture_available(host=host)


_capture_active = False


def set_capture_active(active: bool) -> None:
    """标记 iOS 屏幕采集（AVFoundation / CoreMediaIO）当前是否活跃。

    采集会让 macOS 激活 iPhone 的 QuickTime 屏幕录制 USB 配置，设备随之重新枚举，
    已建立的 go-ios RSD 用户态隧道会失效。WDA 准备阶段据此**强制重建隧道**，否则
    ``runwda`` 会连到过期的 RSD（``could not connect to RSD ... connection refused``）。
    """
    global _capture_active
    _capture_active = bool(active)


def capture_active() -> bool:
    return _capture_active


def mirror_strict_mode() -> bool:
    """调试时为 True：禁用高帧→MJPEG 自动回退，便于暴露采集根因。"""
    raw = os.getenv("IOS_MIRROR_STRICT", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def allows_mjpeg_fallback() -> bool:
    """生产默认 True：高帧启动/断流重试仍失败后回退 MJPEG 9100。"""
    return not mirror_strict_mode()
