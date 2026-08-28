"""选机列表友好名（机型/设备名）纯函数回归。"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def test_android_picker_line() -> bool:
    from autopilot.mobile.device_info import device_picker_line

    with patch("autopilot.mobile.device_info._android_prop_first",
               return_value="Pixel 8"):
        line = device_picker_line("Android", "SERIAL123")
    ok = line == "Pixel 8  (SERIAL123)"
    print("Android 选机行:", "✅" if ok else "❌", line)
    return ok


def test_ios_picker_line() -> bool:
    from autopilot.mobile.device_info import device_picker_line

    with patch("autopilot.mobile.device_info._ios_picker_caption",
               return_value="iPhone 15 Pro · 测试机"):
        line = device_picker_line("iOS", "00008140-AAA")
    ok = "iPhone 15 Pro" in line and "00008140-AAA" in line
    print("iOS 选机行:", "✅" if ok else "❌", line)
    return ok


def test_choose_device_with_friendly_udid_return() -> bool:
    from autopilot.ui.main_window.device_select import choose_device

    labels_seen = []

    def ask(labels, _idx):
        labels_seen.extend(labels)
        return "IOSU"  # values 回调回传纯 UDID

    st, pick = choose_device(
        ["AND1"], ["IOSU"], current="IOSU",
        ask=ask,
        label_fn=lambda p, u: f"{p} · FakeModel  ({u})",
        ask_returns_udid=True,
    )
    ok = (st == "ok" and pick == ("iOS", "IOSU")
          and any("FakeModel" in x for x in labels_seen))
    print("choose_device 友好名+UDID回传:", "✅" if ok else "❌", pick, labels_seen)
    return ok


def test_friendly_pick_labels_matches_inspector_style() -> bool:
    from autopilot.ui.main_window.device_select import friendly_pick_labels

    with patch(
        "autopilot.mobile.device_info.device_picker_line",
        side_effect=lambda plat, u: f"iPhone 15 Pro Max  ({u})",
    ):
        labels = friendly_pick_labels("ios", ["00008140-AAA", "00008130-BBB"])
    ok = (
        labels[0].startswith("iOS · iPhone 15 Pro Max")
        and "00008140-AAA" in labels[0]
        and labels[1].startswith("iOS · iPhone 15 Pro Max")
        and "00008130-BBB" in labels[1]
    )
    print("friendly_pick_labels:", "✅" if ok else "❌", labels)
    return ok


def main() -> int:
    ok = all([
        test_android_picker_line(),
        test_ios_picker_line(),
        test_choose_device_with_friendly_udid_return(),
        test_friendly_pick_labels_matches_inspector_style(),
    ])
    print("\n总结:", "✅ 选机友好名全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
