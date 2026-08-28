"""屏幕录像关键字：Android Appium / iOS go-ios 分支与资源门禁。"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.mobile.session import (
    start_screen_record,
    stop_screen_record,
)
from autopilot.keywords.registry import KeywordError
from autopilot.mobile.ios_screen_record import probe_ios_screen_record


def _mgr(platform: str = "android"):
    m = MagicMock()
    m.platform = platform
    m.backend = "appium"
    m.udid = "00008140-0010000000000001"
    return m


def test_ios_unavailable_when_no_goios() -> bool:
    ctx = ExecutionContext()
    ctx.set_var("__device_udid__", "00008140-0010000000000001")
    with (
        patch(
            "autopilot.keywords.mobile.session.get_manager",
            return_value=_mgr("ios"),
        ),
        patch(
            "autopilot.mobile.ios_screen_record.probe_ios_screen_record",
            return_value=(False, "未找到 go-ios 二进制，iOS 屏幕录像关键字不可用"),
        ),
    ):
        try:
            start_screen_record(ctx)
        except KeywordError as e:
            ok = "不可用" in str(e) and "go-ios" in str(e)
            print("iOS 资源不全门禁:", "✅" if ok else "❌", e)
            return ok
    print("iOS 资源不全门禁: ❌ 未抛错")
    return False


def test_ios_start_stop_mocked() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        ctx = ExecutionContext()
        ctx.set_var("__project_path__", tmp)
        ctx.set_var("__device_udid__", "00008140-0010000000000001")
        out_holder: dict[str, str] = {}

        def _fake_start(_udid, out_path, log=None, fps=12.0, **_kw):
            _ = log, fps
            out_holder["path"] = out_path
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(b"ios-fake-mp4")
            return MagicMock(path=out_path, source="goios")

        def _fake_stop(_udid, ignore_missing=False, join_timeout=6.0):
            _ = _udid, ignore_missing, join_timeout
            return out_holder["path"]

        with (
            patch(
                "autopilot.keywords.mobile.session.get_manager",
                return_value=_mgr("ios"),
            ),
            patch(
                "autopilot.mobile.ios_screen_record.probe_ios_screen_record",
                return_value=(True, ""),
            ),
            patch(
                "autopilot.mobile.ios_screen_record.start_ios_screen_record",
                side_effect=_fake_start,
            ),
            patch(
                "autopilot.mobile.ios_screen_record.stop_ios_screen_record",
                side_effect=_fake_stop,
            ),
        ):
            start_screen_record(ctx)
            out = stop_screen_record(ctx, select_if_timestamp="否", outVar="rec")
        path = out.get("rec") or ""
        ok = os.path.isfile(path) and open(path, "rb").read() == b"ios-fake-mp4"
        print("iOS start/stop mock:", "✅" if ok else "❌", path)
        return ok


def test_stop_writes_evidence_mp4() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        ctx = ExecutionContext()
        ctx.set_var("__project_path__", tmp)
        ctx.set_var("__device_udid__", "emulator-5554")
        ctx.set_var("__mobile_screen_recording__", "android")
        payload = base64.b64encode(b"fake-mp4-bytes").decode("ascii")
        drv = MagicMock()
        drv.stop_recording_screen.return_value = payload
        with (
            patch(
                "autopilot.keywords.mobile.session.get_manager",
                return_value=_mgr("android"),
            ),
            patch("autopilot.keywords.mobile.session._drv", return_value=drv),
        ):
            out = stop_screen_record(
                ctx,
                fileName="",
                select_if_timestamp="否",
                outVar="rec",
            )
        path = out.get("rec") or ""
        evidence = os.path.join(tmp, "reports", "evidence")
        ok = (
            path.startswith(evidence)
            and path.endswith(".mp4")
            and "5554" in path
            and os.path.isfile(path)
            and open(path, "rb").read() == b"fake-mp4-bytes"
        )
        print("Android 落盘 evidence mp4:", "✅" if ok else "❌", path)
        return ok


def test_start_passes_time_limit() -> bool:
    ctx = ExecutionContext()
    drv = MagicMock()
    with (
        patch(
            "autopilot.keywords.mobile.session.get_manager",
            return_value=_mgr("android"),
        ),
        patch("autopilot.keywords.mobile.session._drv", return_value=drv),
    ):
        start_screen_record(ctx, timeLimit="60", bitRate="4000000")
    kwargs = drv.start_recording_screen.call_args.kwargs
    ok = kwargs.get("timeLimit") == "60" and kwargs.get("bitRate") == "4000000"
    print("Android start 传参:", "✅" if ok else "❌", kwargs)
    return ok


def test_probe_returns_tuple() -> bool:
    ok_flag, reason = probe_ios_screen_record()
    ok = isinstance(ok_flag, bool) and isinstance(reason, str)
    print(
        "probe 返回类型:",
        "✅" if ok else "❌",
        ok_flag,
        (reason[:80] if reason else ""),
    )
    return ok


def main() -> int:
    checks = [
        test_ios_unavailable_when_no_goios(),
        test_ios_start_stop_mocked(),
        test_stop_writes_evidence_mp4(),
        test_start_passes_time_limit(),
        test_probe_returns_tuple(),
    ]
    ok = all(checks)
    print("\n总结:", "✅ 屏幕录像全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
