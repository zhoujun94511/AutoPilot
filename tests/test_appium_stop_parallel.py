"""多机并行下 appium_stop 只停本设备端口，不再跳过。"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.mobile.session import appium_stop


def test_appium_stop_runs_in_parallel() -> bool:
    ctx = ExecutionContext()
    ctx.set_var("__parallel_device_udids__", ["U1", "U2"])
    mgr = MagicMock()
    with patch("autopilot.keywords.mobile.session.get_manager", return_value=mgr):
        appium_stop(ctx)
    ok = mgr.stop_server.call_count == 1
    print("并行仍执行 appium_stop（本设备端口）:", "✅" if ok else "❌")
    return ok


def test_appium_stop_runs_when_serial() -> bool:
    ctx = ExecutionContext()
    ctx.set_var("__parallel_device_udids__", ["U1"])
    mgr = MagicMock()
    with patch("autopilot.keywords.mobile.session.get_manager", return_value=mgr):
        appium_stop(ctx)
    ok = mgr.stop_server.call_count == 1
    print("串行执行 appium_stop:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_appium_stop_runs_in_parallel(), test_appium_stop_runs_when_serial()])
    print("\n总结:", "✅ appium_stop 设备级隔离全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
