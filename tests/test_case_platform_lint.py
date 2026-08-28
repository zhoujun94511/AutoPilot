"""用例平台 lint 回归（离线）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def test_xml_platforms_attribute() -> bool:
    from autopilot.metadata import load_catalog

    cat = load_catalog()
    press = cat.get("mobile_presskey")
    toast = cat.get("mobile_toast_verify")
    touch = cat.get("mobile_commActionTouch")
    ok = (
        press is not None
        and not press.platforms
        and "ios" in press.target_platforms
        and toast is not None
        and toast.platforms == ["android"]
        and touch is not None
        and "ios" in touch.target_platforms
    )
    print("XML platforms 属性:", "OK" if ok else "FAIL")
    return ok


def test_lint_ios_case_with_android_keyword() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.testcase import Shell, Step, TestCase

    cat = load_catalog()
    tc = TestCase(name="ios-demo", platform="ios")
    tc.case = Shell("case", steps=[
        Step(keyword_id="mobile_app_start", is_run=True),
        Step(keyword_id="mobile_toast_verify", is_run=True, comment="Android toast"),
    ])
    issues = lint_testcase(tc, cat)
    ok = len(issues) == 1 and issues[0].keyword_id == "mobile_toast_verify"
    print("iOS 用例 lint Android-only:", "OK" if ok else "FAIL", issues)
    return ok


def test_lint_skips_when_no_platform() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.testcase import Shell, Step, TestCase

    cat = load_catalog()
    tc = TestCase(name="generic")
    tc.case = Shell("case", steps=[Step(keyword_id="mobile_presskey", is_run=True)])
    ok = lint_testcase(tc, cat) == []
    print("无 platform 跳过 lint:", "OK" if ok else "FAIL")
    return ok


def test_lint_ios_locator_resource_id() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.testcase import ParamValue, Shell, Step, TestCase

    cat = load_catalog()
    tc = TestCase(name="ios-loc", platform="ios")
    tc.case = Shell("case", steps=[
        Step(
            keyword_id="mobile_element_click",
            is_run=True,
            params=[ParamValue("locator", "xpath:://*[@resource-id='com.x:id/btn']")],
        ),
    ])
    issues = lint_testcase(tc, cat)
    ok = (
        len(issues) == 1
        and issues[0].issue_type == "locator"
        and "resource-id" in issues[0].reason
    )
    print("iOS 用例 resource-id 定位符 lint:", "OK" if ok else "FAIL", issues)
    return ok


def test_all_android_only_xml_marked() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.keyword_platforms import ANDROID_ONLY_KEYWORD_IDS

    cat = load_catalog()
    missing = [
        kid for kid in sorted(ANDROID_ONLY_KEYWORD_IDS)
        if cat.get(kid) is None or cat.get(kid).platforms != ["android"]
    ]
    ok = not missing
    print("Android-only XML 标记完整:", "OK" if ok else f"FAIL {missing}")
    return ok


def test_map_ref_ios_missing_platform_slot() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.mapfile import Locator, MapElement, MapFile
    from autopilot.model.testcase import ParamValue, Shell, Step, TestCase

    cat = load_catalog()
    mf = MapFile(name="login")
    mf.elements.append(MapElement(
        name="btn",
        locators_by_platform={"android": Locator(type="ID", value="com.x:id/btn")},
    ))
    tc = TestCase(name="ios-map", platform="ios")
    tc.case = Shell("case", steps=[
        Step(
            keyword_id="mobile_element_click",
            is_run=True,
            params=[ParamValue("locator", "map::login::btn")],
        ),
    ])
    issues = lint_testcase(tc, cat, maps=[mf])
    ok = (
        len(issues) == 1
        and issues[0].issue_type == "map"
        and "仅有 Android" in issues[0].reason
    )
    print("map:: iOS 缺平台槽位 lint:", "OK" if ok else "FAIL", issues)
    return ok


def test_map_ref_element_not_found() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.mapfile import MapFile
    from autopilot.model.testcase import ParamValue, Shell, Step, TestCase

    cat = load_catalog()
    mf = MapFile(name="login")
    tc = TestCase(name="ios-map2", platform="ios")
    tc.case = Shell("case", steps=[
        Step(
            keyword_id="mobile_element_click",
            is_run=True,
            params=[ParamValue("locator", "map::login::missing")],
        ),
    ])
    issues = lint_testcase(tc, cat, maps=[mf])
    ok = len(issues) == 1 and "元素未找到" in issues[0].reason
    print("map:: 元素不存在 lint:", "OK" if ok else "FAIL", issues)
    return ok


def test_map_ref_ios_wda_backend_mismatch() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.mapfile import Locator, MapElement, MapFile
    from autopilot.model.testcase import ParamValue, Shell, Step, TestCase

    cat = load_catalog()
    mf = MapFile(name="ui")
    mf.elements.append(MapElement(
        name="tab",
        locators_by_platform={
            "ios_appium": Locator(type="NAME", value="Mirroring"),
        },
    ))
    tc = TestCase(name="ios-wda-map", platform="ios")
    tc.case = Shell("case", steps=[
        Step(
            keyword_id="mobile_element_click",
            is_run=True,
            params=[ParamValue("locator", "map::ui::tab")],
        ),
    ])
    issues = lint_testcase(tc, cat, maps=[mf], ios_backend_mode="wda")
    ok = (
        len(issues) == 1
        and issues[0].issue_type == "map"
        and "ios_appium" in issues[0].reason
        and "WDA-direct" in issues[0].reason
    )
    print("map:: ios_wda/ios_appium 后端槽位 lint:", "OK" if ok else "FAIL", issues)
    return ok


def test_all_ios_only_xml_marked() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.keyword_platforms import IOS_ONLY_KEYWORD_IDS

    cat = load_catalog()
    missing = [
        kid for kid in sorted(IOS_ONLY_KEYWORD_IDS)
        if cat.get(kid) is None or cat.get(kid).platforms != ["ios"]
    ]
    ok = not missing
    print("iOS-only XML 标记完整:", "OK" if ok else f"FAIL {missing}")
    return ok


def test_lint_android_case_with_ios_keyword() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.testcase import Shell, Step, TestCase

    cat = load_catalog()
    tc = TestCase(name="android-demo", platform="android")
    tc.case = Shell("case", steps=[
        Step(keyword_id="mobile_app_start", is_run=True),
        Step(keyword_id="ios_alert_handle", is_run=True, comment="iOS alert"),
    ])
    issues = lint_testcase(tc, cat)
    ok = len(issues) == 1 and issues[0].keyword_id == "ios_alert_handle"
    print("Android 用例 lint iOS-only:", "OK" if ok else "FAIL", issues)
    return ok


def test_lint_http_case_with_mobile_keyword() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.case_platform_lint import lint_testcase
    from autopilot.model.testcase import Shell, Step, TestCase

    cat = load_catalog()
    tc = TestCase(name="api-demo", platform="http")
    tc.case = Shell("case", steps=[
        Step(keyword_id="http_get", is_run=True),
        Step(keyword_id="mobile_app_start", is_run=True, comment="误用移动关键字"),
    ])
    issues = lint_testcase(tc, cat)
    ok = any(i.keyword_id == "mobile_app_start" for i in issues)
    assert ok, issues
    print("HTTP 用例 lint 移动关键字:", "OK" if ok else "FAIL", issues)
    return ok


def main() -> int:
    ok = all([
        test_xml_platforms_attribute(),
        test_lint_ios_case_with_android_keyword(),
        test_lint_skips_when_no_platform(),
        test_lint_ios_locator_resource_id(),
        test_all_android_only_xml_marked(),
        test_all_ios_only_xml_marked(),
        test_lint_android_case_with_ios_keyword(),
        test_lint_http_case_with_mobile_keyword(),
        test_map_ref_ios_missing_platform_slot(),
        test_map_ref_element_not_found(),
        test_map_ref_ios_wda_backend_mismatch(),
    ])
    print("\n总结:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
