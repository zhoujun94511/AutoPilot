"""UI 错误文案清洗（离线单测）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autopilot.ui.errors import clean_driver_err


def test_session_terminated_ios_wda() -> bool:
    e = RuntimeError("A session is either terminated or not started")
    msg = clean_driver_err(e, "iOS", "wda")
    ok = "WDA" in msg and "会话" in msg
    print("iOS WDA 会话断开:", "✅" if ok else "❌", msg)
    return ok


def test_session_terminated_ios_appium() -> bool:
    e = RuntimeError("NoSuchDriverError: session is either terminated or not started")
    msg = clean_driver_err(e, "iOS", "appium")
    ok = "Appium" in msg and "XCUITest" in msg
    print("iOS Appium 会话断开:", "✅" if ok else "❌", msg)
    return ok


def test_econnrefused_android() -> bool:
    e = ConnectionError("Failed to establish a new connection: ECONNREFUSED")
    msg = clean_driver_err(e, "Android", "appium")
    ok = "4723" in msg
    print("Android ECONNREFUSED:", "✅" if ok else "❌", msg)
    return ok


def test_truncates_long_message() -> bool:
    e = RuntimeError("x" * 300)
    msg = clean_driver_err(e)
    ok = len(msg) == 160
    print("长消息截断 160:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_session_terminated_ios_wda(),
        test_session_terminated_ios_appium(),
        test_econnrefused_android(),
        test_truncates_long_message(),
    ])
    print("\n总结:", "✅ UI 错误文案全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
