"""device_readiness 纯逻辑单测。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_device_lists_and_resolve() -> bool:
    from autopilot.ui.main_window.device_readiness import DeviceLists, resolve_udid

    d = DeviceLists.from_lists(["A1"], ["I1", "I2"])
    ok = (
        d.has_mobile()
        and d.for_platform("Android") == ["A1"]
        and d.for_platform("ios") == ["I1", "I2"]
        and resolve_udid("Android", "", d) == "A1"
        and resolve_udid("iOS", "", d) == ""
        and resolve_udid("iOS", "I2", d) == "I2"
    )
    print("DeviceLists + resolve_udid:", "✅" if ok else "❌")
    return ok


def test_validate_inspect_target() -> bool:
    from autopilot.ui.main_window.device_readiness import (
        DeviceLists, validate_inspect_target, no_mobile_message,
    )

    empty = DeviceLists.from_lists([], [])
    ios_only = DeviceLists.from_lists([], ["U1"])
    both = DeviceLists.from_lists(["A1"], ["U1"])

    web_ok, _ = validate_inspect_target("Web", "", empty)
    none_ok, msg0 = validate_inspect_target("Android", "", empty)
    ios_auto, _ = validate_inspect_target("iOS", "", ios_only)
    wrong_plat, msg1 = validate_inspect_target("Android", "", ios_only)
    offline, msg2 = validate_inspect_target("iOS", "GONE", ios_only)
    multi, msg3 = validate_inspect_target("iOS", "", DeviceLists.from_lists([], ["U1", "U2"]))
    ok_pick, _ = validate_inspect_target("Android", "A1", both)

    ok = all([
        web_ok,
        not none_ok and no_mobile_message() in msg0,
        ios_auto,
        not wrong_plat and "iOS" in msg1,
        not offline and "不在线" in msg2,
        not multi and "多台" in msg3,
        ok_pick,
    ])
    print("validate_inspect_target:", "✅" if ok else "❌")
    return ok


def test_mirror_gone_and_defaults() -> bool:
    from autopilot.ui.main_window.device_readiness import (
        DeviceLists, mirror_device_gone, default_inspect_platform_index,
    )

    d = DeviceLists.from_lists(["A1"], ["U1"])
    ok = all([
        mirror_device_gone("android", "A1", d) is False,
        mirror_device_gone("android", "A1", DeviceLists.from_lists([], ["U1"])) is True,
        mirror_device_gone("android", "", DeviceLists.from_lists([], [])) is True,
        default_inspect_platform_index(DeviceLists.from_lists([], [])) == 2,
        default_inspect_platform_index(DeviceLists.from_lists(["A"], [])) == 0,
        default_inspect_platform_index(DeviceLists.from_lists([], ["U"])) == 1,
    ])
    print("mirror_gone + default_index:", "✅" if ok else "❌")
    return ok


def test_runtime_run_helpers() -> bool:
    from autopilot.ui.main_window.device_readiness import (
        DeviceLists, auto_run_udid, missing_runtime_platforms,
        present_runtime_platforms,
    )

    ios_only = DeviceLists.from_lists([], ["U1"])
    both = DeviceLists.from_lists(["A1"], ["U1", "U2"])

    ok = all([
        present_runtime_platforms(ios_only) == {"ios"},
        missing_runtime_platforms({"android", "ios"}, ios_only) == {"android"},
        missing_runtime_platforms({"ios"}, ios_only) == set(),
        auto_run_udid("ios", ios_only) == "U1",
        auto_run_udid("ios", both, inspect_platform="iOS", inspect_udid="U2") == "U2",
        auto_run_udid("android", both) == "A1",
        auto_run_udid("ios", both) is None,
    ])
    print("runtime 运行设备解析:", "✅" if ok else "❌")
    return ok


def test_ios_install_pick() -> bool:
    from autopilot.ui.main_window.device_readiness import DeviceLists, ios_install_pick_status

    ok1, u1 = ios_install_pick_status(DeviceLists.from_lists([], ["U1"]))
    ok2, _ = ios_install_pick_status(DeviceLists.from_lists([], ["U1", "U2"]))
    ok3, _ = ios_install_pick_status(DeviceLists.from_lists([], []))
    ok = ok1 == ("ok", "U1") and ok2 == ("multi", "") and ok3 == ("manual", "")
    print("iOS 装包选设备:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_device_lists_and_resolve(),
        test_validate_inspect_target(),
        test_mirror_gone_and_defaults(),
        test_runtime_run_helpers(),
        test_ios_install_pick(),
    ])
    print("\n总结:", "✅ device_readiness 全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
