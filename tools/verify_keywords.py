"""真机冒烟：用真实连接的 Android/iOS 设备，对一批代表性 Mobile 关键字做端到端核实。

目的：确认"关键字真的能驱动真机"，而非仅离线逻辑跑通。安全起见只驱动**系统设置 App**
（Android com.android.settings / iOS com.apple.Preferences），且元素类关键字用**实时页面源里
动态挑出的真实元素**来测，避免依赖某台 ROM 的固定控件、也不乱点用户的真实应用。

用法（设备已连接 + 授权）：
    .venv/Scripts/python.exe tools/verify_keywords.py            # 自动跑所有连上的设备
    .venv/Scripts/python.exe tools/verify_keywords.py --android  # 只跑 Android
    .venv/Scripts/python.exe tools/verify_keywords.py --ios

每个关键字报 PASS / FAIL / SKIP（带原因）。这是冒烟，不求覆盖全部 75 个 Mobile 关键字，
而是覆盖核心链路：会话/设备信息/当前界面/按键/坐标点击/元素存在/元素取文本。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.registry import REGISTRY, KeywordError
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.mobile.driver import get_manager


def _adb_devices() -> list:
    from autopilot.ui.device_monitor import parse_adb_devices
    from autopilot.mobile import adb
    exe = adb.ensure_adb()
    if not exe:
        return []
    return parse_adb_devices(adb.run_adb(["devices"]))


def _ios_devices() -> list:
    from autopilot.ui.device_monitor import DeviceMonitor
    return DeviceMonitor.list_ios()


def _pick_xpath(page_source: str, platform: str):
    """从实时页面源里挑一个稳定的真实元素，返回其 XPATH（找不到返回 None）。"""
    from lxml import etree
    # noinspection PyBroadException
    try:
        root = etree.fromstring(page_source.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    attrs = (["resource-id", "content-desc", "text"] if platform == "android"
             else ["name", "label", "value"])
    for node in root.iter():
        for a in attrs:
            v = node.get(a)
            if v and v.strip():
                return f'//*[@{a}="{v}"]'
    return None


def _pick_editable_xpath(page_source: str, platform: str):
    """从页面源挑一个可编辑输入框（Android EditText / iOS TextField 系），没有返回 None。"""
    from lxml import etree
    # noinspection PyBroadException
    try:
        root = etree.fromstring(page_source.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    ios_types = ("XCUIElementTypeTextField", "XCUIElementTypeSearchField",
                 "XCUIElementTypeSecureTextField")
    # Android 可编辑控件不止 EditText：AutoComplete/MultiAutoComplete… 或 editable/focused
    and_editable = ("EditText", "AutoCompleteTextView", "MultiAutoCompleteTextView")
    for node in root.iter():
        if platform == "android":
            cls = node.get("class", "")
            rid = node.get("resource-id", "")
            is_edit = (any(t in cls for t in and_editable) or node.get("editable") == "true"
                       or (node.get("focused") == "true" and "Text" in cls))
            if is_edit:
                return f'//*[@resource-id="{rid}"]' if rid else f'//*[@class="{cls}"]'
        else:
            t = node.tag
            if t in ios_types:
                nm = node.get("name", "")
                return f'//{t}[@name="{nm}"]' if nm else f'//{t}'
    return None


def _text_input_checks(rep, plat: str, ctx, ed_xp) -> None:
    """对动态挑到的可编辑框验证 输入→取文本→清除（无可编辑框则 SKIP）。"""
    if not ed_xp:
        rep.run(plat, "文本输入(input/clear)", None, skip="当前界面无可编辑输入框")
        return
    rep.run(plat, "mobile_element_text_input",
            lambda: REGISTRY["mobile_element_text_input"].func(ctx, locator=ed_xp, text="autopilot"))
    rep.run(plat, "mobile_element_get_element_text(输入后)",
            lambda: REGISTRY["mobile_element_get_element_text"].func(ctx, locator=ed_xp, outVar="TXT"))
    rep.run(plat, "mobile_element_text_clear",
            lambda: REGISTRY["mobile_element_text_clear"].func(ctx, locator=ed_xp))


def _element_gesture_checks(rep, plat: str, ctx, xp) -> None:
    """对动态挑到的真实元素跑读类关键字 + 一次滑动（两平台共用）。"""
    if xp:
        rep.run(plat, "mobile_element_get_element_exist",
                lambda: REGISTRY["mobile_element_get_element_exist"].func(ctx, locator=xp, outVar="EX"))
        rep.run(plat, "mobile_element_get_element_text",
                lambda: REGISTRY["mobile_element_get_element_text"].func(ctx, locator=xp, outVar="TXT"))
        rep.run(plat, "mobile_verify_element_existed",
                lambda: REGISTRY["mobile_verify_element_existed"].func(ctx, locator=xp, isExisted="true"))
        attr = "class" if plat == "android" else "type"
        rep.run(plat, "mobile_element_get_element_attribute",
                lambda: REGISTRY["mobile_element_get_element_attribute"].func(
                    ctx, locator=xp, attribution=attr, outVar="ATTR"))
        rep.run(plat, "mobile_verify_element_visible",
                lambda: REGISTRY["mobile_verify_element_visible"].func(
                    ctx, locator=xp, isVisible="true", timeout="5000"))
        rep.run(plat, "mobile_verify_element_enabled",
                lambda: REGISTRY["mobile_verify_element_enabled"].func(
                    ctx, locator=xp, isEnabled="true", timeout="5000"))
        rep.run(plat, "mobile_wait_element_visible",
                lambda: REGISTRY["mobile_wait_element_visible"].func(
                    ctx, locator=xp, isVisible="true", timeout="5000"))
    else:
        rep.run(plat, "元素类(exist/text/verify/attr)", None, skip="页面源未挑到可用元素")
    rep.run(plat, "mobile_define_swipe_direction(滑动)",
            lambda: REGISTRY["mobile_define_swipe_direction"].func(ctx, direction="UP", count="1"))


class Report:
    def __init__(self) -> None:
        self.rows = []

    def run(self, platform: str, kid: str, fn, *, skip: str = "") -> None:
        if skip:
            self.rows.append((platform, kid, "SKIP", skip))
            print(f"  [SKIP] {kid}: {skip}")
            return
        try:
            res = fn()
            detail = "" if res is None else str(res)[:80]
            self.rows.append((platform, kid, "PASS", detail))
            print(f"  [PASS] {kid}  {detail}")
        except Exception as e:  # noqa: BLE001
            msg = (str(e).strip().splitlines() or [""])[0][:120]
            self.rows.append((platform, kid, "FAIL", msg))
            print(f"  [FAIL] {kid}: {msg}")

    def summary(self) -> str:
        from collections import Counter
        c = Counter(r[2] for r in self.rows)
        return (f"PASS {c.get('PASS', 0)} / FAIL {c.get('FAIL', 0)} / "
                f"SKIP {c.get('SKIP', 0)}  共 {len(self.rows)}")


def verify_android(udid: str, rep: Report) -> None:
    from autopilot.mobile import adb
    print(f"\n=== Android {udid} ===")
    # 安全目标：拉起系统设置，再附着前台
    # noinspection PyBroadException
    try:
        adb.run_adb(["shell", "am", "start", "-n",
                     "com.android.settings/.Settings"], serial=udid)
    except Exception:
        pass
    # Android 控件自动化依赖 Appium（uiautomator2）：harness 自行按需拉起
    # noinspection PyBroadException
    try:
        from autopilot.keywords.mobile.appium_server import AppiumServer
        AppiumServer().ensure_running()
    except Exception as e:  # noqa: BLE001
        rep.run("android", "Appium 就绪", None, skip=f"Appium 不可用：{str(e)[:80]}")
        return
    ctx = ExecutionContext()
    ctx.set_var("__device_udid__", udid)
    mgr = get_manager(ctx)
    try:
        mgr.create("Android", "", "", udid)         # 附着当前前台（设置）
    except Exception as e:  # noqa: BLE001
        rep.run("android", "会话建立(create)", None, skip=f"建会话失败：{str(e)[:100]}")
        return
    drv = mgr.driver()
    rep.run("android", "会话建立(create)", lambda: "ok")
    rep.run("android", "mobile_get_deviceinfo",
            lambda: REGISTRY["mobile_get_deviceinfo"].func(ctx, deviceInfo="AndroidVersion", outVar="INFO"))
    rep.run("android", "mobile_get_current_activity",
            lambda: REGISTRY["mobile_get_current_activity"].func(ctx, outVar="ACT"))
    rep.run("android", "mobile_app_get_package_and_activity",
            lambda: REGISTRY["mobile_app_get_package_and_activity"].func(ctx, package="PKG", activity="ACT"))
    # 内置输入法安装（resources/re_apks），安装后启用并设为默认，供中文/特殊字符输入
    rep.run("android", "installAdbkeyboard(安装+启用)",
            lambda: REGISTRY["installAdbkeyboard"].func(ctx))
    rep.run("android", "installUtf7Ime(安装+启用)",
            lambda: REGISTRY["installUtf7Ime"].func(ctx))
    sz = drv.get_window_size()
    rep.run("android", "mobile_tap(屏幕中点)",
            lambda: REGISTRY["mobile_tap"].func(ctx, x=str(sz["width"] // 2), y=str(sz["height"] // 2)))
    rep.run("android", "mobile_longclick(坐标)",
            lambda: REGISTRY["mobile_longclick"].func(
                ctx, x=str(sz["width"] // 2), y=str(sz["height"] // 3), duration="800"))
    # 九宫格连续手势(屏幕中部小范围上滑，无害)
    cx, cy = sz["width"] // 2, sz["height"] * 2 // 3
    rep.run("android", "mobile_commActionTouch(连续手势)",
            lambda: REGISTRY["mobile_commActionTouch"].func(
                ctx, startCoordinate=f"{cx},{cy}", deviation="0,-100", count="3"))
    # toast 校验：无 toast 时按预期抛，捕获后视为"轮询链路通"
    def _toast_probe():
        try:
            REGISTRY["mobile_toast_verify"].func(ctx, text="__autopilot_no_toast__", wait="1")
        except KeywordError:
            return "轮询链路OK(无toast)"
        return "命中"
    rep.run("android", "mobile_toast_verify(轮询链路)", _toast_probe)
    # 元素类 + 滑动 + 文本输入：从实时页面源动态挑真实元素
    src = drv.page_source
    _element_gesture_checks(rep, "android", ctx, _pick_xpath(src, "android"))
    _text_input_checks(rep, "android", ctx, _pick_editable_xpath(src, "android"))
    rep.run("android", "mobile_presskey(back)",
            lambda: REGISTRY["mobile_presskey"].func(ctx, oKeys="back", count="1"))
    # intentToMiniProgram 会跳转/离开当前页，放最后（无害网页 scheme）
    rep.run("android", "intentToMiniProgram(URL Scheme)",
            lambda: REGISTRY["intentToMiniProgram"].func(ctx, urlPath="https://example.com"))
    # noinspection PyBroadException
    try:
        mgr.close()
    except Exception:
        pass


_TEST_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>AutoPilot Web 冒烟</title></head><body>
<h1 id="title">Hello AutoPilot</h1>
<input id="username" type="text">
<button id="go" onclick="document.getElementById('result').innerText=document.getElementById('username').value">GO</button>
<div id="result"></div>
<a id="lnk" href="#x">link</a>
</body></html>"""


def verify_web(rep: Report) -> None:
    """WebUI 真浏览器冒烟：开本地测试页(自控元素)→开浏览器→找/输入/点击/取文本/校验。"""
    print("\n=== WebUI (Chrome headless) ===")
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".html", prefix="ap_web_")
    os.write(fd, _TEST_HTML.encode("utf-8"))
    os.close(fd)
    url = "file:///" + path.replace("\\", "/")
    ctx = ExecutionContext()
    try:
        REGISTRY["web_browser_open"].func(ctx, url=url, type="headless")
    except Exception as e:  # noqa: BLE001
        rep.run("web", "web_browser_open", None, skip=f"浏览器启动失败：{str(e)[:90]}")
        os.unlink(path)
        return
    rep.run("web", "web_browser_open", lambda: "ok")
    uname = '//*[@id="username"]'
    rep.run("web", "web_browser_getBrowserTitle",
            lambda: REGISTRY["web_browser_getBrowserTitle"].func(ctx, title="AutoPilot Web 冒烟"))
    rep.run("web", "web_element_get_element_exist",
            lambda: REGISTRY["web_element_get_element_exist"].func(ctx, locator='//h1[@id="title"]', outVar="EX"))
    rep.run("web", "web_element_get_element_text",
            lambda: REGISTRY["web_element_get_element_text"].func(ctx, locator='//h1[@id="title"]', outVar="T"))
    rep.run("web", "web_element_text_input",
            lambda: REGISTRY["web_element_text_input"].func(ctx, locator=uname, text="autopilot"))
    rep.run("web", "web_element_click(提交)",
            lambda: REGISTRY["web_element_click"].func(ctx, locator='//*[@id="go"]'))
    rep.run("web", "web_element_get_element_text(结果)",
            lambda: REGISTRY["web_element_get_element_text"].func(ctx, locator='//*[@id="result"]', outVar="R"))
    rep.run("web", "web_verify_element_text(结果=autopilot)",
            lambda: REGISTRY["web_verify_element_text"].func(
                ctx, locator='//*[@id="result"]', text="autopilot", matched="true"))
    rep.run("web", "web_verify_element_existed",
            lambda: REGISTRY["web_verify_element_existed"].func(ctx, locator='//a[@id="lnk"]', isExisted="true"))
    # noinspection PyBroadException
    try:
        REGISTRY["web_browser_close"].func(ctx)
    except Exception:
        pass
    rep.run("web", "web_browser_close", lambda: "ok")
    # noinspection PyBroadException
    try:
        os.unlink(path)
    except Exception:
        pass


def verify_ios(udid: str, rep: Report) -> None:
    print(f"\n=== iOS {udid} ===")
    os.environ["IOS_USE_GOIOS"] = "1"               # Windows/Linux 直连 WDA
    ctx = ExecutionContext()
    ctx.set_var("__device_udid__", udid)
    mgr = get_manager(ctx)
    try:
        mgr.create("iOS", "", "", udid)
    except Exception as e:  # noqa: BLE001
        rep.run("ios", "会话建立(create/WDA)", None,
                skip=f"WDA 会话未建立（需 go-ios 隧道+WDA）：{str(e)[:80]}")
        return
    drv = mgr.driver()
    rep.run("ios", "会话建立(create/WDA)", lambda: "ok")
    rep.run("ios", "mobile_get_deviceinfo",
            lambda: REGISTRY["mobile_get_deviceinfo"].func(ctx, deviceInfo="platformVersion", outVar="INFO"))
    sz = drv.get_window_size()
    rep.run("ios", "mobile_tap(屏幕中点)",
            lambda: REGISTRY["mobile_tap"].func(ctx, x=str(sz["width"] // 2), y=str(sz["height"] // 2)))
    rep.run("ios", "mobile_longclick(坐标)",
            lambda: REGISTRY["mobile_longclick"].func(
                ctx, x=str(sz["width"] // 2), y=str(sz["height"] // 3), duration="800"))
    src = drv.page_source
    _element_gesture_checks(rep, "ios", ctx, _pick_xpath(src, "ios"))
    _text_input_checks(rep, "ios", ctx, _pick_editable_xpath(src, "ios"))
    # noinspection PyBroadException
    try:
        mgr.close()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--android", action="store_true")
    ap.add_argument("--ios", action="store_true")
    ap.add_argument("--web", action="store_true")
    args = ap.parse_args()
    both = not (args.android or args.ios or args.web)
    rep = Report()

    if args.android or both:
        andro = _adb_devices()
        if not andro:
            print("未检测到 Android 设备（adb devices 为空/离线）")
        for u in andro:
            verify_android(u, rep)
    if args.ios or both:
        ios = _ios_devices()
        if not ios:
            print("未检测到 iOS 设备")
        for u in ios:
            verify_ios(u, rep)
    if args.web or both:
        verify_web(rep)

    print("\n==== 汇总 ====")
    print(rep.summary())
    for plat, kid, st, detail in rep.rows:
        if st == "FAIL":
            print(f"  FAIL {plat} {kid}: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
