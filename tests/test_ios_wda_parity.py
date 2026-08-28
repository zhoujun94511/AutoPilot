"""WDA-direct 对齐回归：属性映射、滚动、Bundle 解析（离线）。"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def test_ios_attr_content_desc() -> bool:
    from autopilot.mobile.ios.attributes import read_element_attribute

    el = MagicMock()
    el.size = {"height": 10, "width": 20}
    el.location = {"x": 1, "y": 2}
    el.text = ""
    el.get_attribute.side_effect = lambda n: {"label": "OK"}.get(n)

    val = read_element_attribute(el, "content-desc", platform="ios")
    ok = val == "OK"
    print("ios attr content-desc→label:", "OK" if ok else f"FAIL {val!r}")
    return ok


def test_ios_attr_android_path() -> bool:
    from autopilot.mobile.ios.attributes import read_element_attribute

    el = MagicMock()
    el.size = {"height": 1, "width": 1}
    el.location = {"x": 0, "y": 0}
    el.text = "t"
    el.get_attribute.return_value = "rid"

    val = read_element_attribute(el, "resource-id", platform="android")
    el.get_attribute.assert_called_with("resourceId")
    ok = val == "rid"
    print("android attr resource-id:", "OK" if ok else "FAIL")
    return ok


def test_scroll_until_found() -> bool:
    from autopilot.mobile.ios.scroll import scroll_until_element_found

    calls = {"n": 0}

    def try_find():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("not yet")
        return SimpleNamespace(is_displayed=lambda: True)

    swipes = []
    el = scroll_until_element_found(
        SimpleNamespace(), "wda",
        try_find=try_find,
        swipe=lambda: swipes.append(1),
        max_attempts=5,
        pause_s=0,
    )
    ok = calls["n"] == 2 and len(swipes) == 1 and el is not None
    print("scroll_until_element_found:", "OK" if ok else "FAIL")
    return ok


def test_ios_pkg_without_appfile() -> bool:
    from autopilot.keywords.mobile.session import app_get_package_and_activity
    from autopilot.keywords.context import ExecutionContext
    from autopilot.keywords.mobile import driver as drv_mod

    ctx = ExecutionContext()
    ctx.set_var("app_package", "com.test.app")
    mgr = drv_mod.get_manager(ctx)
    mgr.platform = "ios"
    mgr._driver = SimpleNamespace(
        capabilities={"bundleId": "com.test.app"},
        _bundle_id="com.test.app",
    )
    mgr._has_driver = True
    mgr.backend = "wda"

    out = app_get_package_and_activity(ctx)
    ok = out.get("app_package") == "com.test.app" and out.get("app_activity") == ""
    print("ios get_package no appFile:", "OK" if ok else f"FAIL {out}")
    return ok


def test_ios_alert_xml_platforms() -> bool:
    from autopilot.metadata import load_catalog

    cat = load_catalog()
    for kid in ("ios_alert_handle", "ios_alert_set_policy"):
        meta = cat.get(kid)
        ok_one = meta is not None and meta.platforms == ["ios"]
        if not ok_one:
            print("ios_alert xml:", f"FAIL {kid}")
            return False
    print("ios_alert xml platforms=ios:", "OK")
    return True


def test_ios_device_info_lookup() -> bool:
    from autopilot.mobile.ios.device_info import lookup_ios_device_info, wda_status_to_device_info

    info = wda_status_to_device_info({
        "os": {"version": "17.0", "sdkVersion": "17.0", "name": "iOS"},
        "device": "iPhone",
        "ios": {"ip": "192.168.1.2"},
        "build": {"version": "1.22"},
    })
    ok = info["version"] == "17.0" and info["ip"] == "192.168.1.2"

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Drv:
        capabilities = {"platformName": "iOS"}

        def device_info(self):
            return info

    val = lookup_ios_device_info(_Drv(), "AndroidVersion")
    ok = ok and val == "17.0"
    print("ios device_info lookup:", "OK" if ok else "FAIL")
    return ok


def test_gesture_swipe_element_wda() -> bool:
    from autopilot.mobile.ios.gesture import swipe_element
    from unittest.mock import MagicMock

    el = MagicMock()
    el.id = "e1"
    el.rect = {"x": 10, "y": 20, "width": 100, "height": 50}
    client = MagicMock()
    drv = MagicMock(wda_client=client, _c=client)
    client.element_swipe = MagicMock()

    swipe_element(drv, el, "左", backend="wda")
    client.element_swipe.assert_called_once_with("e1", "left")
    print("gesture swipe_element wda:", "OK")
    return True


def test_ios_only_keyword_platforms() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.keyword_platforms import IOS_ONLY_KEYWORD_IDS, platform_mismatch_reason

    cat = load_catalog()
    meta = cat.get("ios_alert_handle")
    ok = (
        meta is not None
        and meta.platforms == ["ios"]
        and "ios_alert_handle" in IOS_ONLY_KEYWORD_IDS
        and platform_mismatch_reason("android", meta).startswith("iOS 专有")
    )
    print("IOS_ONLY 元数据:", "OK" if ok else "FAIL")
    return ok


def main() -> int:
    ok = all([
        test_ios_attr_content_desc(),
        test_ios_attr_android_path(),
        test_scroll_until_found(),
        test_ios_pkg_without_appfile(),
        test_ios_alert_xml_platforms(),
        test_ios_device_info_lookup(),
        test_gesture_swipe_element_wda(),
        test_ios_only_keyword_platforms(),
    ])
    print("\n总结:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
