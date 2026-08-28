"""截屏默认路径在多机下带设备标识。"""

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
from autopilot.keywords.mobile.session import app_snapshot


def test_snapshot_path_includes_udid() -> bool:
    ctx = ExecutionContext()
    udid = "00008140-0010000000000001"
    ctx.set_var("__device_udid__", udid)
    drv = MagicMock()
    captured = {}

    def _save(save_path):
        captured["path"] = save_path
        return True

    drv.get_screenshot_as_file.side_effect = _save
    with patch("autopilot.keywords.mobile.session._drv", return_value=drv):
        app_snapshot(ctx, fileName="", select_if_timestamp="否")
    shot_path = captured.get("path") or ""
    ok = udid in shot_path or udid[-8:] in shot_path
    print("截屏路径含 UDID 后缀:", "✅" if ok else "❌", shot_path)
    return ok


def main() -> int:
    ok = test_snapshot_path_includes_udid()
    print("\n总结:", "✅ 截屏路径全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
