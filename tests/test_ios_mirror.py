"""iOS 镜像视频源策略（离线可测）：归一化 / 平台解析 / 严格回退开关 / AVF 边界。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autopilot.mobile import ios_mirror as im


def test_mirror_source_normalize() -> bool:
    ok = (im.normalize_mirror_source("") == im.MIRROR_AUTO
          and im.normalize_mirror_source("MJPEG") == im.MIRROR_MJPEG
          # 历史取值 "qvh" 兼容为 auto（Mac 走 AVFoundation）
          and im.normalize_mirror_source("qvh") == im.MIRROR_AUTO
          and im.normalize_mirror_source("bogus") == im.MIRROR_AUTO)
    print("镜像源归一化:", "✅" if ok else "❌")
    return ok


def test_auto_resolves_by_platform() -> bool:
    win = im.resolve_mirror_source(im.MIRROR_AUTO, host="windows") == im.MIRROR_MJPEG
    mac = im.resolve_mirror_source(im.MIRROR_AUTO, host="mac") == im.MIRROR_AUTO
    print("auto 平台解析:", "✅" if win and mac else "❌", "win→mjpeg", "mac→auto")
    return win and mac


def test_strict_fallback_gate() -> bool:
    old = os.environ.pop("IOS_MIRROR_STRICT", None)
    try:
        os.environ["IOS_MIRROR_STRICT"] = "1"
        strict = bool(im.mirror_strict_mode() and not im.allows_mjpeg_fallback())
        del os.environ["IOS_MIRROR_STRICT"]
        prod = bool(im.allows_mjpeg_fallback() and not im.mirror_strict_mode())
        ok = strict and prod
        print("镜像严格/回退开关:", "✅" if ok else "❌", f"strict={strict}", f"prod_fallback={prod}")
    finally:
        if old is not None:
            os.environ["IOS_MIRROR_STRICT"] = old
        elif "IOS_MIRROR_STRICT" in os.environ:
            del os.environ["IOS_MIRROR_STRICT"]
    return ok


def test_avf_mac_only_boundary() -> bool:
    """AVFoundation 仅 Mac 可用；非 Mac 恒不可用（不依赖 helper 是否构建）。"""
    old = os.environ.pop("IOS_MIRROR_SOURCE", None)
    try:
        win_block = not im.can_try_avf_mirror(im.MIRROR_AUTO, host="windows")
        wants_mac = im.wants_highfps_video(im.MIRROR_AUTO, host="mac")
        wants_win = not im.wants_highfps_video(im.MIRROR_AUTO, host="windows")
    finally:
        if old is not None:
            os.environ["IOS_MIRROR_SOURCE"] = old
    ok = bool(win_block and wants_mac and wants_win)
    print("AVF Mac 边界:", "✅" if ok else "❌",
          f"(win_block={win_block}, wants_mac={wants_mac})")
    return ok


def test_build_avf_opts_includes_udid_and_env() -> bool:
    """build_avf_opts 与 _mirror_session / 断流重启共用，须含 UDID 与编码参数。"""
    from unittest.mock import patch

    env_keys = ("IOS_MIRROR_MAX_WIDTH", "IOS_MIRROR_BITRATE", "IOS_MIRROR_FPS")
    saved_env = {k: os.environ.pop(k, None) for k in env_keys}
    try:
        os.environ["IOS_MIRROR_MAX_WIDTH"] = "720"
        os.environ["IOS_MIRROR_BITRATE"] = "8000000"
        os.environ["IOS_MIRROR_FPS"] = "30"
        with patch("autopilot.mobile.ios_mirror.avf_helper_path", return_value="/tmp/ios-avf-capture"):
            opts = im.build_avf_opts("UDID-ABC", grab=lambda: b"")
        grab_fn = opts.get("grab")
        ok = bool(
            opts.get("avf_capture") is True
            and opts.get("avf_helper") == "/tmp/ios-avf-capture"
            and opts.get("avf_unique_id") == "UDID-ABC"
            and opts.get("avf_max_width") == 720
            and opts.get("avf_bitrate") == 8_000_000
            and opts.get("avf_fps") == 30
            and grab_fn is not None
        )
        print("build_avf_opts:", "✅" if ok else "❌")
        return ok
    finally:
        for key, val in saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def main() -> int:
    ok = all([
        test_mirror_source_normalize(),
        test_auto_resolves_by_platform(),
        test_strict_fallback_gate(),
        test_avf_mac_only_boundary(),
        test_build_avf_opts_includes_udid_and_env(),
    ])
    print("\n总结:", "✅ iOS 镜像模块全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
