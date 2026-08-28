"""关键字平台元数据 + iOS 策略共用层回归（离线）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def test_android_only_grey() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.keyword_platforms import platform_mismatch_reason, target_platforms

    cat = load_catalog()
    press = cat.get("mobile_presskey")
    toast = cat.get("mobile_toast_verify")
    start = cat.get("mobile_app_start")
    touch = cat.get("mobile_commActionTouch")
    ok = (
        press is not None
        and not press.platforms
        and "ios" in target_platforms(press)
        and platform_mismatch_reason("ios", press) == ""
        and toast is not None
        and toast.platforms == ["android"]
        and platform_mismatch_reason("ios", toast).startswith("Android 专有")
        and start is not None
        and "ios" in target_platforms(start)
        and platform_mismatch_reason("ios", start) == ""
        and touch is not None
        and "ios" in target_platforms(touch)
    )
    print("Android-only 灰显元数据:", "OK" if ok else "FAIL")
    return ok


def test_webui_web_only() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.keyword_platforms import platform_mismatch_reason, target_platforms

    cat = load_catalog()
    sample = cat.get("web_browser_open")
    ok = (
        sample is not None
        and sample.platforms == ["web"]
        and target_platforms(sample) == frozenset({"web"})
        and bool(platform_mismatch_reason("android", sample))
        and bool(platform_mismatch_reason("ios", sample))
    )
    print("WebUI 仅 Web:", "OK" if ok else "FAIL", sample.keyword_id if sample else "?")
    return ok


def test_ios_strategies_shared() -> bool:
    from autopilot.mobile.ios_strategies import (
        attr_find_strategies, dedupe_strategies, text_find_strategies,
    )

    wda = text_find_strategies("OK", wda_first=True)
    appium = text_find_strategies("OK", wda_first=False)
    ok = (
        len(dedupe_strategies(wda)) == len(wda)
        and wda[0].by == "link text"
        and appium[0].by == "accessibility id"
    )
    attrs = attr_find_strategies("label", "Go", wda_first=True)
    ok = ok and attrs[0].by == "link text" and attrs[0].value == "label=Go"
    print("ios_strategies 共用层:", "OK" if ok else "FAIL")
    return ok


def main() -> int:
    ok = all([test_android_only_grey(), test_webui_web_only(), test_ios_strategies_shared()])
    print("\n总结:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
