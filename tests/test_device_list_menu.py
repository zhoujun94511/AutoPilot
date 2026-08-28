"""已连接设备枢纽入口白盒：列表数据、菜单构建、顶层菜单收敛、Chip 槽。"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_list_connected_devices() -> bool:
    from autopilot.ui.device_list_menu import list_connected_devices
    got = list_connected_devices(["a1", ""], ["i1", "  "])
    ok = (len(got) == 2
          and got[0].platform == "Android" and got[0].udid == "a1"
          and got[1].platform == "iOS" and got[1].udid == "i1"
          and got[0].label == "Android · a1")
    print("list_connected_devices:", "✅" if ok else "❌", got)
    return ok


def test_is_current_inspect_target() -> bool:
    from autopilot.ui.device_list_menu import (
        ConnectedDevice, is_current_inspect_target,
    )
    d = ConnectedDevice("Android", "dev1")
    ok = (
        is_current_inspect_target(
            d, inspect_chosen=True, inspect_platform="Android",
            inspect_udid="dev1") is True
        and is_current_inspect_target(
            d, inspect_chosen=False, inspect_platform="Android",
            inspect_udid="dev1") is False
        and is_current_inspect_target(
            d, inspect_chosen=True, inspect_platform="iOS",
            inspect_udid="dev1") is False
    )
    print("is_current_inspect_target:", "✅" if ok else "❌")
    return ok


def test_build_menu_hub_actions() -> bool:
    """枢纽：子菜单含设检视/信息/镜像；无底部 Web/装包、无「连接检视设备」。"""
    from PyQt6.QtWidgets import QWidget
    from autopilot.ui.device_list_menu import (
        ConnectedDevice, build_connected_devices_menu,
    )
    _app()
    parent = QWidget()
    seen = {"set": None, "info": None, "mirror": None}

    menu = build_connected_devices_menu(parent, [])
    texts = [a.text() for a in menu.actions()]
    ok_empty = any("无已连接" in t for t in texts)
    ok_no_footer = not any(
        "连接 Web 检视" in t or "安装 iOS" in t or "连接检视设备" in t
        for t in texts)

    devices = [
        ConnectedDevice("Android", "a1"),
        ConnectedDevice("iOS", "i1"),
    ]
    menu2 = build_connected_devices_menu(
        parent, devices,
        inspect_chosen=True, inspect_platform="Android", inspect_udid="a1",
        on_set_inspect=lambda d: seen.__setitem__("set", d.udid),
        on_show_info=lambda d: seen.__setitem__("info", d.udid),
        on_start_mirror=lambda d: seen.__setitem__("mirror", d.udid),
    )
    top2 = [a.text() for a in menu2.actions()]
    ok_no_dup = not any("连接检视设备" in (t or "") for t in top2)
    sub_texts = []
    for act in menu2.actions():
        sub = act.menu()
        if sub is None:
            continue
        for sa in sub.actions():
            sub_texts.append(sa.text() or "")
            if "设为检视" in (sa.text() or "") and sa.isEnabled():
                sa.trigger()
            if "查看设备信息" in (sa.text() or ""):
                sa.trigger()
            if "开始实时镜像" in (sa.text() or ""):
                sa.trigger()
    ok_sub = (
        any("设为检视" in t for t in sub_texts)
        and any("查看设备信息" in t for t in sub_texts)
        and any("开始实时镜像" in t for t in sub_texts)
    )
    ok = (ok_empty and ok_no_footer and ok_no_dup and ok_sub
          and seen["set"] == "i1"
          and seen["info"] in ("a1", "i1")
          and seen["mirror"] in ("a1", "i1"))
    parent.close()
    print("枢纽菜单动作:", "✅" if ok else "❌", seen)
    return ok


def test_top_menu_converged() -> bool:
    """顶层「设备」菜单只保留 list + pkg_info，不重复挂 connect/info/install。"""
    from autopilot.ui.actions import ACTIONS_BY_ID, MENUS
    from autopilot.ui.main_window import MainWindow
    _app()
    device_menu = next(m for m in MENUS if m[0].startswith("设备"))
    ids = [x for x in device_menu[1] if isinstance(x, str)]
    ok_menu = (
        ids == ["device.list", "device.pkg_info"]
        or (set(ids) == {"device.list", "device.pkg_info"}
            and "device.connect" not in ids
            and "device.info" not in ids
            and "device.ios_install" not in ids)
    )
    # 动作仍注册，槽仍可用（枢纽内 / 兼容调用）
    ok_registered = all(
        i in ACTIONS_BY_ID
        for i in ("device.list", "device.pkg_info",
                  "device.connect", "device.info", "device.ios_install")
    )
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        ok_slots = all(
            callable(getattr(win, ACTIONS_BY_ID[i].slot, None))
            for i in ("device.list", "device.pkg_info", "device.connect")
        )
        menu = win._build_connected_devices_menu()
        texts = [a.text() for a in menu.actions()]
        ok_hub = not any(
            "连接 Web 检视" in (t or "") or "连接检视设备" in (t or "")
            for t in texts)
        ok_chip = (hasattr(win, "show_device_chip_menu")
                   and menu is not None
                   and win._sb_device is not None
                   and hasattr(win, "_start_mirror_from_connected")
                   and hasattr(win.mirror, "request_start"))
        win.close()
    ok = ok_menu and ok_registered and ok_slots and ok_chip and ok_hub
    print("顶层菜单收敛:", "✅" if ok else "❌", ids)
    return ok


def test_set_inspect_from_list() -> bool:
    from unittest.mock import MagicMock
    from autopilot.ui.main_window import MainWindow
    from autopilot.ui.device_list_menu import ConnectedDevice
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = (["devA", "devB"], [])
        win.inspector.refresh = MagicMock()
        win._set_inspect_from_connected(ConnectedDevice("Android", "devB"))
        ok = (win._inspect_chosen is True
              and win._inspect_platform == "Android"
              and win._inspect_udid == "devB"
              and win._sb_device.status_state() == "connected"
              and win.inspector.refresh.called)
        win.close()
    print("列表设为检视目标:", "✅" if ok else "❌")
    return ok


def test_start_mirror_from_list_skips_picker() -> bool:
    """枢纽开镜像：写入目标并 request_start，before_start 不弹选。"""
    from unittest.mock import MagicMock
    from autopilot.ui.main_window import MainWindow
    from autopilot.ui.device_list_menu import ConnectedDevice
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = (["devM"], [])
        win._focus_right_view = MagicMock()
        select_mirror = MagicMock(return_value=True)
        win._select_mirror_device = select_mirror
        started = {"n": 0}

        def fake_request_start():
            started["n"] += 1
            # 模拟 MirrorPanel._start → before_start
            assert win._prepare_mirror_start() is True
            assert select_mirror.call_count == 0

        win.mirror.request_start = fake_request_start
        win.mirror.active = MagicMock(return_value=False)
        win._start_mirror_from_connected(ConnectedDevice("Android", "devM"))
        ok = (started["n"] == 1
              and win._inspect_platform == "Android"
              and win._inspect_udid == "devM"
              and win._inspect_chosen is True
              and win._focus_right_view.called
              and getattr(win, "_mirror_from_hub", True) is False)
        win.close()
    print("列表开实时镜像:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_list_connected_devices(),
        test_is_current_inspect_target(),
        test_build_menu_hub_actions(),
        test_top_menu_converged(),
        test_set_inspect_from_list(),
        test_start_mirror_from_list_skips_picker(),
    ])
    print("\n总结:", "✅ 已连接设备枢纽全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
