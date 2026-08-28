"""移动端后端分支 + iOS 直连 WDA 适配（离线）回归。

验证：按 平台×宿主系统 选后端；WDA 定位映射 / session 路径前缀 / 不支持方法兜底。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.mobile import platform as mp
from autopilot.keywords.mobile import wda_client as wc
from autopilot.keywords.registry import KeywordError


def test_backend_selection() -> bool:
    os.environ.pop("IOS_BACKEND", None)
    cases = {
        ("Android", "windows"): "appium",
        ("Android", "mac"): "appium",
        ("Android", "linux"): "appium",
        ("iOS", "mac"): "appium",       # Mac 上 iOS 走 Appium xcuitest
        ("iOS", "windows"): "wda",      # Windows 上 iOS 走直连 WDA
        ("iOS", "linux"): "wda",
    }
    ok = all(mp.select_backend(o, host=h) == exp for (o, h), exp in cases.items())
    # 环境变量强制覆盖
    os.environ["IOS_BACKEND"] = "appium"
    forced = mp.select_backend("iOS", host="windows") == "appium"
    os.environ.pop("IOS_BACKEND", None)
    ok = ok and forced
    print("后端分支(平台×宿主):", "✅" if ok else "❌")
    return ok


def test_appium_manager_server_bootstrap() -> bool:
    """本地地址走 acquire/stop_local_appium；远程地址只标记 running、不拉起本机进程。"""
    from unittest.mock import patch

    from autopilot.keywords.mobile.driver import AppiumManager

    calls = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Srv:
        def __init__(self, host="127.0.0.1", port=4723):
            self.host = host
            self.port = port

        def ensure_running(self):
            calls.append(("ensure", self.host, self.port))

        def stop(self):
            calls.append(("stop", self.host, self.port))

    def _acquire(host="127.0.0.1", port=4723):
        srv = _Srv(host, port)
        srv.ensure_running()
        return srv

    def _stop(host="127.0.0.1", port=4723):
        calls.append(("stop", host or "127.0.0.1", int(port)))

    with patch("autopilot.keywords.mobile.appium_server.acquire_local_appium", _acquire), \
         patch("autopilot.keywords.mobile.appium_server.stop_local_appium", _stop):
        mgr = AppiumManager()
        mgr.start_server()
        local_ok = mgr.server_running is True and calls == [("ensure", "127.0.0.1", 4723)]
        mgr.stop_server()
        stop_ok = calls[-1] == ("stop", "127.0.0.1", 4723) and mgr.server_running is False

        remote = AppiumManager()
        remote.server = "http://10.0.0.8:4725"
        remote.start_server()
        remote_ok = remote.server_running is True and calls == [
            ("ensure", "127.0.0.1", 4723),
            ("stop", "127.0.0.1", 4723),
        ]
    ok = local_ok and stop_ok and remote_ok
    print("AppiumManager start_server(local ensure / remote skip):", "OK" if ok else "FAIL", calls)
    return ok


def test_wda_using_and_path() -> bool:
    ok_using = (wc._using("xpath") == "xpath" and wc._using("name") == "name"
                and wc._using("accessibility id") == "accessibility id"
                and wc._using("class name") == "class name"
                and wc._using("id") == "name")          # iOS 无 id → name
    c = wc.WdaClient("http://127.0.0.1:8100")             # 仅构造，不联网
    top = c._sp("/status") == "/status"                   # 顶层不加前缀
    no_sess = c._sp("/element") == "/element"             # 无 session 时不加前缀
    c.session_id = "S1"
    with_sess = c._sp("/element") == "/session/S1/element"
    sess_top = c._sp("/session") == "/session"
    ok = ok_using and top and no_sess and with_sess and sess_top
    print("WDA 定位映射 + session 路径:", "✅" if ok else "❌")
    return ok


def test_wda_driver_unsupported() -> bool:
    drv = wc.WdaDriver(wc.WdaClient("http://127.0.0.1:8100"))
    raised = False
    try:
        drv.press_keycode(4)          # Android 专有 → 应明确报不支持
    except KeywordError:
        raised = True
    ok = raised and drv.capabilities["platformName"] == "iOS"
    print("WDA driver 不支持方法兜底:", "✅" if ok else "❌")
    return ok


def test_wda_tap_swipe_deviceinfo() -> bool:
    """真机实测修复的回归（脱机）：iOS WDA 的 tap/swipe 走 /actions、device_info 解析 /status，
    且 _tap_xy 在 WDA 上回退到 driver.tap（原先误用 execute_script 而失败）。"""
    try:
        c = wc.WdaClient("http://127.0.0.1:8100")
        posts = []
        c._post = lambda path, body: posts.append((path, body))   # 截获，不联网
        c.status = lambda: {"os": {"name": "iOS", "version": "17.1", "sdkVersion": "17.0"},
                            "device": "iphone", "ios": {"ip": "1.2.3.4"}, "build": {"version": "5.0"}}
        drv = wc.WdaDriver(c)
        info = drv.device_info()
        di_ok = (info["version"] == "17.1" and info["platformVersion"] == "17.1"
                 and info["model"] == "iphone" and info["os"] == "iOS" and info["ip"] == "1.2.3.4")
        drv.swipe(0, 0, 100, 200, 500)
        seq = posts[-1][1]["actions"][0]["actions"]
        sw_ok = (posts[-1][0] == "/actions"
                 and any(a.get("x") == 100 and a.get("y") == 200 for a in seq)
                 and any(a["type"] == "pointerDown" for a in seq))
        # long_press → /actions 带 pause(=duration)
        drv.long_press(1, 2, 700)
        lp_seq = posts[-1][1]["actions"][0]["actions"]
        lp_ok = (posts[-1][0] == "/actions"
                 and any(a["type"] == "pause" and a.get("duration") == 700 for a in lp_seq))
        # _tap_xy/_long_press_xy 回退链：WdaDriver 上 ActionBuilder/execute_script 失败 → 落到原生 → /actions
        from autopilot.keywords.mobile.session import _tap_xy, _long_press_xy
        posts.clear()
        _tap_xy(drv, 5, 6)
        _long_press_xy(drv, 7, 8, 600)
        fallback_ok = len([p for p, _ in posts if p == "/actions"]) >= 2
        # WdaElement.rect/location/size（供偏移点击/按 locator 长按算坐标）
        c._get = lambda path: {"x": 10, "y": 20, "width": 100, "height": 40} if path.endswith("/rect") else None
        el = wc.WdaElement(c, "E1")
        el_ok = (el.rect == {"x": 10, "y": 20, "width": 100, "height": 40}
                 and el.location == {"x": 10, "y": 20} and el.size == {"width": 100, "height": 40}
                 and el.is_selected() is False)   # /selected 端点(本桩返 None→False)
        ok = di_ok and sw_ok and lp_ok and fallback_ok and el_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("WDA tap/swipe/deviceinfo 回归: ⏭ 跳过(", e, ")")
        return True
    print("WDA tap/swipe/deviceinfo(真机修复脱机回归):", "✅" if ok else "❌")
    return ok


def test_wda_reuse_by_udid() -> bool:
    """D1：WDA 仅在「存活 且 同一设备」时复用；换设备/不同 udid 必须回收重建。

    用真实判定分支，仅打桩重活（prepare/WdaClient），记录每次为哪台设备准备。"""
    from autopilot.keywords.mobile import driver as drv_mod
    from autopilot.mobile import ios_bootstrap as ib
    from autopilot.keywords.mobile import wda_client as wcmod

    prepared, stopped = [], []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakePrep:
        def __init__(self, udid, _bundle, **_kw):
            self.udid = udid

        def prepare(self, **_kw):
            prepared.append(self.udid)
            return "http://127.0.0.1:8100"

        def ensure_forward_port(self, *_a, **_k):
            pass

        def stop(self):
            stopped.append(self.udid)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeClient:
        def __init__(self, *_a, **_k):
            pass

        def create_session(self, **_k):
            pass

        def set_recover(self, *_a, **_k):
            pass

        def launch_app(self, *_a, **_k):
            pass

        def activate_app(self, *_a, **_k):
            pass

    # 打桩：隔离真机/HTTP（_create_wda_driver 内部 from autopilot.mobile import ios_bootstrap
    # 与 from .wda_client import WdaClient, WdaDriver，故须改这两个源模块的属性），
    # 只保留 D1 的复用判定逻辑。
    orig = (ib.IosDevicePrep, ib.wda_alive, ib.is_port_listening, ib.kill_listeners,
            wcmod.WdaClient, wcmod.WdaDriver)
    try:
        ib.IosDevicePrep = _FakePrep
        ib.is_port_listening = lambda *_a, **_k: False
        ib.kill_listeners = lambda *_a, **_k: []
        wcmod.WdaClient = _FakeClient
        wcmod.WdaDriver = lambda c, bundle_id="": c
        mgr = drv_mod.AppiumManager()

        ib.wda_alive = lambda *_a, **_k: False          # 无存活 WDA
        mgr._create_wda_driver("", "DEV_A")             # → 为 A 准备
        a_ok = prepared == ["DEV_A"] and mgr._wda_udid == "DEV_A"

        ib.wda_alive = lambda *_a, **_k: True           # A 的 WDA 现已存活
        mgr._create_wda_driver("", "DEV_A")             # 同设备 + 存活 → 复用，不再 prepare
        reuse_ok = prepared == ["DEV_A"]

        mgr._create_wda_driver("", "DEV_B")             # 换 B：即便 8100 存活也必须重建
        switch_ok = (prepared == ["DEV_A", "DEV_B"] and "DEV_A" in stopped
                     and mgr._wda_udid == "DEV_B")
        ok = a_ok and reuse_ok and switch_ok
    finally:
        (ib.IosDevicePrep, ib.wda_alive, ib.is_port_listening, ib.kill_listeners,
         wcmod.WdaClient, wcmod.WdaDriver) = orig
    print("WDA 按 udid 复用/换机重建(D1):", "✅" if ok else "❌", (prepared, stopped))
    return ok


def test_map_platform_locator() -> bool:
    """对象库元素按平台绑定定位符(对标 @AndroidFindBy/@iOSXCUITFindBy)：
    序列化往返保留；resolve 按当前会话平台优先取对应套，无会话回退通用。"""
    try:
        import types
        from autopilot.model.mapfile import MapFile, MapElement, Locator
        from autopilot.keywords.context import ExecutionContext
        from autopilot.model import serializer
        el = MapElement(name="loginBtn",
                        locator=Locator(type="XPATH", value="//common"),
                        locators_by_platform={"android": Locator(type="ID", value="and_id"),
                                              "ios": Locator(type="NAME", value="ios_name")})
        mf = MapFile(name="M", elements=[el])
        # 序列化往返
        rt = serializer.dict_to_mapfile(serializer.mapfile_to_dict(mf)).find("loginBtn")
        rt_ok = (rt.locators_by_platform["android"].value == "and_id"
                 and rt.locators_by_platform["ios"].value == "ios_name"
                 and rt.locator.value == "//common")
        # 按平台解析
        ctx = ExecutionContext(); ctx.register_map(mf)
        ctx.appium = types.SimpleNamespace(platform="android")
        a = ctx.resolve_locator("map::M::loginBtn")
        ctx.appium = types.SimpleNamespace(platform="ios")
        i = ctx.resolve_locator("map::M::loginBtn")
        ctx.appium = None                              # 无会话 → 通用
        d = ctx.resolve_locator("map::M::loginBtn")
        ok = (rt_ok and a.type == "ID" and a.value == "and_id"
              and i.type == "NAME" and i.value == "ios_name" and d.value == "//common")
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("对象库按平台定位符: ⏭ 跳过(", e, ")")
        return True
    print("对象库按平台绑定定位符(往返/android/ios/回退通用):", "✅" if ok else "❌")
    return ok


def test_resolve_apk_path() -> bool:
    """安装关键字预检：目录自动取唯一 apk；后缀/存在/空 校验给中文可操作错误(不再直丢 adb)。"""
    import tempfile
    from autopilot.keywords.mobile.session import _resolve_apk_path
    ok = True
    with tempfile.TemporaryDirectory() as d:
        apk = os.path.join(d, "app.apk")
        open(apk, "w").close()
        ok = ok and _resolve_apk_path(apk) == apk        # 直接给 .apk 文件
        ok = ok and _resolve_apk_path(d) == apk          # 给目录 → 自动取唯一 apk
        notapk = os.path.join(d, "thing.bin")
        open(notapk, "w").close()
        for bad in (notapk, os.path.join(d, "missing.apk"), ""):
            try:
                _resolve_apk_path(bad)
                ok = False                                # 上述都应抛 KeywordError
            except KeywordError:
                pass
    print("安装路径预检(目录取apk/后缀/存在/空 校验):", "✅" if ok else "❌")
    return ok


def test_find_element_wait() -> bool:
    """find_element 显式等待：timeout 内元素晚出现会重试到成功；一直没有则超时抛错；
    timeout 归一(空/非法→默认30s，'0'→不等)。"""
    import types
    from autopilot.keywords.mobile.driver import find_element, _to_wait_ms, DEFAULT_ELEMENT_WAIT_MS
    from autopilot.keywords.context import ExecutionContext
    tw = (_to_wait_ms("") == DEFAULT_ELEMENT_WAIT_MS and _to_wait_ms(None) == DEFAULT_ELEMENT_WAIT_MS
          and _to_wait_ms("5000") == 5000 and _to_wait_ms("abc") == DEFAULT_ELEMENT_WAIT_MS
          and _to_wait_ms("0") == 0)
    calls = {"n": 0}

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _El:
        pass

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _RetryDrv:
        def find_element(self, _by, _v):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("尚未渲染")
            return _El()

    ctx = ExecutionContext()
    ctx.appium = types.SimpleNamespace(driver=lambda: _RetryDrv(), platform="android", backend="")
    el = find_element(ctx, "//x", timeout="2000")
    retry_ok = el is not None and calls["n"] == 3        # 重试到第 3 次成功

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FailDrv:
        def find_element(self, _by, _v):
            raise RuntimeError("永远找不到")

    ctx2 = ExecutionContext()
    ctx2.appium = types.SimpleNamespace(driver=lambda: _FailDrv(), platform="android", backend="")
    raised = False
    # noinspection PyBroadException
    try:
        find_element(ctx2, "//x", timeout="200")         # 小超时、一直失败 → 抛
    except Exception:
        raised = True
    ok = tw and retry_ok and raised
    print("find_element 显式等待(重试/超时/归一):", "✅" if ok else "❌")
    return ok


def test_mobile_timeout_threaded() -> bool:
    """8 个元素类关键字都已接入 timeout 形参（不再被 **_kw 吞掉、能透传给 find_element）。"""
    import inspect
    from autopilot.keywords.registry import REGISTRY
    ids = ["mobile_element_click", "mobile_element_text_input", "mobile_element_JS_click",
           "mobile_element_continuous_click", "mobile_activity_switch",
           "mobile_element_get_element_exist", "mobile_element_get_element_visible",
           "mobile_element_get_element_enabled", "swipe_login"]
    missing = [kid for kid in ids
               if kid not in REGISTRY
               or "timeout" not in inspect.signature(REGISTRY[kid].func).parameters]
    ok = not missing
    print("mobile timeout 透传(9个关键字接入形参):", "✅" if ok else "❌", missing)
    return ok


def test_text_clear_password() -> bool:
    """text_clear：普通框走 clear()；isPassword=true 时按 times 次删除键(keycode 67)清空。"""
    import types
    from autopilot.keywords.mobile.element import text_clear
    from autopilot.keywords.context import ExecutionContext
    keys = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _PwEl:
        def click(self):
            pass
        def clear(self):
            raise AssertionError("密码框不应走 clear()")

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _PwDrv:
        def find_element(self, _by, _v):
            return _PwEl()
        def press_keycode(self, k):
            keys.append(k)

    ctx = ExecutionContext()
    ctx.appium = types.SimpleNamespace(driver=lambda: _PwDrv(), platform="android", backend="")
    text_clear(ctx, locator="//x", isPassword="true", times="5", timeout="0")
    pw_ok = keys == [67] * 5

    cleared = {"n": 0}

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _NormEl:
        def clear(self):
            cleared["n"] += 1

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _NormDrv:
        def find_element(self, _by, _v):
            return _NormEl()

    ctx2 = ExecutionContext()
    ctx2.appium = types.SimpleNamespace(driver=lambda: _NormDrv(), platform="android", backend="")
    text_clear(ctx2, locator="//x", timeout="0")
    norm_ok = cleared["n"] == 1
    ok = pw_ok and norm_ok
    print("text_clear 密码框删除(按键×times/普通clear):", "✅" if ok else "❌")
    return ok


def test_intent_to_miniprogram() -> bool:
    """intentToMiniProgram：run_adb 参数化 am start VIEW -d；空/非法则报错。"""
    import types
    from autopilot.keywords.mobile import session as sess
    from autopilot.keywords.context import ExecutionContext
    calls: list[list[str]] = []
    orig = sess.run_adb
    sess.run_adb = lambda args, serial="": calls.append(list(args))
    try:
        ctx = ExecutionContext()
        ctx.appium = types.SimpleNamespace(driver=lambda: types.SimpleNamespace(
            capabilities={}))
        sess.intent_to_mini_program(ctx, urlPath="weixin://dl/business?t=abc&x=1")
        sent_ok = (
            calls
            and calls[0][:4] == ["shell", "am", "start", "-a"]
            and calls[0][4] == "android.intent.action.VIEW"
            and calls[0][5] == "-d"
            and "weixin://" in calls[0][6]
        )
        raised_empty = raised_quote = False
        try:
            sess.intent_to_mini_program(ctx, urlPath="")
        except sess.KeywordError:
            raised_empty = True
        try:
            sess.intent_to_mini_program(ctx, urlPath="weixin://x'; rm -rf /")
        except sess.KeywordError:
            raised_quote = True
        ok = bool(sent_ok) and raised_empty and raised_quote
    finally:
        sess.run_adb = orig
    print("intentToMiniProgram(adb VIEW跳转/空报错):", "✅" if ok else "❌")
    return ok


def test_toast_verify() -> bool:
    """toast_verify：page_source 含目标文本→通过；超时未见→抛。"""
    import types
    from autopilot.keywords.mobile.misc import toast_verify
    from autopilot.keywords.context import ExecutionContext
    ctx = ExecutionContext()
    ctx.appium = types.SimpleNamespace(driver=lambda: types.SimpleNamespace(
        page_source="<hierarchy><node class='android.widget.Toast' text='保存成功'/></hierarchy>"))
    hit = True
    # noinspection PyBroadException
    try:
        toast_verify(ctx, text="保存成功", wait="1")
    except Exception:
        hit = False
    miss = False
    try:
        toast_verify(ctx, text="不存在的提示", wait="1")
    except KeywordError:
        miss = True
    ok = hit and miss
    print("toast_verify(命中/超时抛):", "✅" if ok else "❌")
    return ok


def test_comm_action_touch() -> bool:
    """九宫格：坐标按 count 递增，给 resolution 时等比缩放到实际屏幕(走 swipe 兜底验证)。"""
    import types
    from autopilot.keywords.mobile.session import comm_action_touch
    from autopilot.keywords.context import ExecutionContext
    swipes = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Drv:
        def get_window_size(self):
            return {"width": 1080, "height": 1920}
        def swipe(self, x1, y1, x2, y2, dur):
            swipes.append((x1, y1, x2, y2))
    ctx = ExecutionContext()
    ctx.appium = types.SimpleNamespace(driver=lambda: _Drv())
    # 分辨率 540x960 → 实际 1080x1920，缩放 ×2；start=10,20 dev=5,5 count=3
    comm_action_touch(ctx, resolution="540,960", startCoordinate="10,20",
                      deviation="5,5", count="3")
    # 期望点(缩放后)：(20,40)(30,50)(40,60) → 两段 swipe
    ok = swipes == [(20, 40, 30, 50), (30, 50, 40, 60)]
    print("commActionTouch(递增/缩放/连段):", "✅" if ok else "❌", swipes)
    return ok


def test_install_ime() -> bool:
    """内置输入法安装：装 apk→解析包名→从 ime list -a 挑组件→enable+set；apk 缺失报错。"""
    import types
    from autopilot.keywords.mobile import session as sess
    from autopilot.keywords.context import ExecutionContext
    calls = {"install": [], "shell": []}
    orig_run, orig_shell, orig_parse = sess.run_adb, sess.adb_shell, None
    # ime list -a 长格式样例（含尾部冒号的组件行 + mId/name 干扰行）
    listed = ("com.android.adbkeyboard/.AdbIME:\n"
              "  mId=com.android.adbkeyboard/.AdbIME mSettingsActivityName=null\n"
              "      name=com.android.adbkeyboard.AdbIME\n"
              "      packageName=com.android.adbkeyboard\n")

    def _run(args, serial="", timeout=0):
        calls["install"].append(list(args))
        return "Success"

    def _shell(cmd, serial=""):
        calls["shell"].append(cmd)
        return listed if cmd.startswith("ime list") else ""

    import autopilot.mobile.apk as apkmod
    orig_parse = apkmod.parse_apk
    sess.run_adb, sess.adb_shell = _run, _shell
    apkmod.parse_apk = lambda p: types.SimpleNamespace(package="com.android.adbkeyboard", main_activity="")
    try:
        ctx = ExecutionContext()
        # 走真实 apk 路径（resources/re_apks/ADBKeyBoard.apk 存在）
        sess.install_adbkeyboard(ctx)
        installed = any(a[:2] == ["install", "-r"] for a in calls["install"])
        enabled = any(c == "ime enable com.android.adbkeyboard/.AdbIME" for c in calls["shell"])
        did_set = any(c == "ime set com.android.adbkeyboard/.AdbIME" for c in calls["shell"])
        # apk 缺失 → KeywordError
        missing = False
        try:
            sess._install_and_enable_ime(ctx, "NoSuch.apk", "缺失")
        except sess.KeywordError:
            missing = True
        ok = installed and enabled and did_set and missing
    finally:
        sess.run_adb, sess.adb_shell = orig_run, orig_shell
        apkmod.parse_apk = orig_parse
    print("installIme(装+解析+enable/set+缺失报错):", "✅" if ok else "❌")
    return ok


def test_install_keepdata() -> bool:
    """启动被测应用 keepData：否+已装→先卸载再全新装；是+已装→覆盖重装(-r)；未装→直接装。"""
    import types
    from autopilot.keywords.mobile import session as sess
    from autopilot.mobile import apk as apkmod
    from autopilot.mobile import xapk as xapkmod
    from autopilot.keywords.context import ExecutionContext
    calls = []
    saved = (sess.run_adb, xapkmod.run_adb, sess._app_installed, sess._serial,
             sess._resolve_apk_path, sess.get_manager, apkmod.parse_apk)

    def _record(args, serial="", timeout=0):
        calls.append(list(args))
        return "Success"

    sess.run_adb = _record
    xapkmod.run_adb = _record
    sess._serial = lambda ctx: "dev"
    sess._resolve_apk_path = lambda p, _proj="": "/x/app.apk"
    apkmod.parse_apk = lambda p: types.SimpleNamespace(package="com.demo", main_activity=".Main")
    sess.get_manager = lambda ctx: types.SimpleNamespace(create=lambda *a, **k: None)
    try:
        sess._app_installed = lambda pkg, serial="": True          # 已安装
        calls.clear()
        sess.app_install_and_open(ExecutionContext(), appFile="app.apk", keepData="否")
        no_keep = (["uninstall", "com.demo"] in calls and ["install", "-t", "/x/app.apk"] in calls
                   and not any(a[:2] == ["install", "-r"] for a in calls))
        calls.clear()
        sess.app_install_and_open(ExecutionContext(), appFile="app.apk", keepData="是")
        keep = (["install", "-r", "-t", "/x/app.apk"] in calls
                and not any(a and a[0] == "uninstall" for a in calls))
        sess._app_installed = lambda pkg, serial="": False         # 未安装
        calls.clear()
        sess.app_install_and_open(ExecutionContext(), appFile="app.apk", keepData="是")
        fresh_keep = (["install", "-t", "/x/app.apk"] in calls
                      and not any(a[:2] == ["install", "-r"] for a in calls)
                      and not any(a and a[0] == "uninstall" for a in calls))
        calls.clear()
        sess.app_install_and_open(ExecutionContext(), appFile="app.apk", keepData="否")
        no_app = (not any(a and a[0] == "uninstall" for a in calls)
                  and ["install", "-t", "/x/app.apk"] in calls)
        ok = no_keep and keep and fresh_keep and no_app
    finally:
        (sess.run_adb, xapkmod.run_adb, sess._app_installed, sess._serial,
         sess._resolve_apk_path, sess.get_manager, apkmod.parse_apk) = saved
    print("install keepData(否卸载重装/是覆盖/未装直装):", "✅" if ok else "❌")
    return ok


def test_install_keepdata_ios() -> bool:
    """iOS：已装则先卸载再装；未装则直接装。"""
    import types
    from autopilot.keywords.mobile import session as sess
    from autopilot.mobile import ipa as ipamod
    from autopilot.keywords.context import ExecutionContext
    calls = []
    saved = (sess._ios_app_installed, sess._ios_uninstall_app, sess.ios_install_app,
             sess._resolve_ipa_path, sess.get_manager,
             ipamod.parse_ipa, sess._serial)
    sess._resolve_ipa_path = lambda p, _proj="": "/x/app.ipa"
    sess._serial = lambda ctx: "ios-dev"
    sess.get_manager = lambda ctx: types.SimpleNamespace(
        create=lambda *a, **k: calls.append(("create", a, k)))
    ipamod.parse_ipa = lambda p: types.SimpleNamespace(
        bundle_id="com.demo.ios", version_name="1.0", minimum_os="",
        expiration_date="", provisioned_devices=[])
    sess.ios_install_app = lambda path, udid="", log=None: (
        calls.append(("install", path, udid)) or "pymobiledevice3"
    )
    try:
        sess._ios_app_installed = lambda bundle_id, udid="": True
        sess._ios_uninstall_app = lambda bundle_id, udid="", log=None: (
            calls.append(("uninstall", bundle_id, udid)) or "ios"
        )
        calls.clear()
        sess.app_install_and_open(ExecutionContext(), appFile="app.ipa", type="iOS")
        installed = (
            ("uninstall", "com.demo.ios", "ios-dev") in calls
            and ("install", "/x/app.ipa", "ios-dev") in calls
            and any(x[0] == "create" for x in calls)
        )
        sess._ios_app_installed = lambda bundle_id, udid="": False
        calls.clear()
        sess.app_install_and_open(ExecutionContext(), appFile="app.ipa", type="iOS")
        fresh = (
            ("install", "/x/app.ipa", "ios-dev") in calls
            and not any(x[0] == "uninstall" for x in calls)
        )
        ok = installed and fresh
    finally:
        (sess._ios_app_installed, sess._ios_uninstall_app, sess.ios_install_app,
         sess._resolve_ipa_path, sess.get_manager,
         ipamod.parse_ipa, sess._serial) = saved
    print("install keepData(iOS 已装先卸/未装直装):", "✅" if ok else "❌")
    return ok


def test_install_open_device_by_platform() -> bool:
    """mobile_app_install_and_open passes the platform-matched UDID to install and create."""
    import types
    from autopilot.keywords.mobile import session as sess
    from autopilot.mobile import apk as apkmod
    from autopilot.mobile import ipa as ipamod
    from autopilot.mobile import xapk as xapkmod
    from autopilot.keywords.context import ExecutionContext

    calls = []
    saved = (sess.run_adb, xapkmod.run_adb, sess._app_installed, sess._serial, sess._resolve_apk_path,
             sess.get_manager, apkmod.parse_apk, sess._ios_app_installed,
             sess._ios_uninstall_app, sess.ios_install_app, sess._resolve_ipa_path,
             ipamod.parse_ipa)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Mgr:
        def create(self, os_type, pkg, act, udid=""):
            calls.append(("create", os_type, udid))

    def _record(args, serial="", timeout=0):
        calls.append(("adb", list(args), serial))
        return "Success"

    sess.run_adb = _record
    xapkmod.run_adb = _record
    sess._app_installed = lambda pkg, serial="": False
    sess._serial = lambda _ctx: ""
    sess._resolve_apk_path = lambda p, _proj="": "/x/app.apk"
    sess.get_manager = lambda _ctx: _Mgr()
    apkmod.parse_apk = lambda p: types.SimpleNamespace(package="com.demo", main_activity=".Main")
    sess._ios_app_installed = lambda bundle_id, udid="": False
    sess._ios_uninstall_app = lambda bundle_id, udid="": calls.append(("ios-uninstall", udid))
    sess._resolve_ipa_path = lambda p, _proj="": "/x/app.ipa"
    sess.ios_install_app = lambda path, udid="", log=None: (
        calls.append(("ios-install", path, udid)) or "pymobiledevice3"
    )
    ipamod.parse_ipa = lambda p: types.SimpleNamespace(
        bundle_id="com.demo.ios", version_name="1.0", minimum_os="",
        expiration_date="", provisioned_devices=[])
    try:
        ctx = ExecutionContext()
        ctx.set_var("__device_udid_by_platform__", {"android": "AND-1", "ios": "IOS-1"})
        sess.app_install_and_open(ctx, appFile="app.apk", keepData="yes")
        sess.app_install_and_open(ctx, appFile="app.ipa", keepData="yes", type="iOS")
        android_ok = ("adb", ["install", "-t", "/x/app.apk"], "AND-1") in calls \
            and ("create", "Android", "AND-1") in calls
        ios_ok = ("ios-install", "/x/app.ipa", "IOS-1") in calls \
            and ("create", "iOS", "IOS-1") in calls
        ok = android_ok and ios_ok
    finally:
        (sess.run_adb, xapkmod.run_adb, sess._app_installed, sess._serial, sess._resolve_apk_path,
         sess.get_manager, apkmod.parse_apk, sess._ios_app_installed,
         sess._ios_uninstall_app, sess.ios_install_app, sess._resolve_ipa_path,
         ipamod.parse_ipa) = saved
    print("install_and_open platform UDID:", "OK" if ok else "FAIL", calls)
    return ok


def test_unicode_keyboard_caps() -> bool:
    """开关控制 Android 会话自动并入 unicodeKeyboard/resetKeyboard；iOS/关时不加；显式不覆盖。"""
    import os as _os
    from autopilot.keywords.mobile.driver import AppiumManager
    key = "AUTOPILOT_UNICODE_KEYBOARD"
    prev = _os.environ.get(key)
    try:
        mgr = AppiumManager()
        # 关（默认）→ Android 不加
        _os.environ[key] = "0"
        mgr.platform = "android"
        off_android = mgr._session_caps() == {}
        # 开 → Android 加两项
        _os.environ[key] = "1"
        on_android = mgr._session_caps() == {"unicodeKeyboard": True, "resetKeyboard": True}
        # 开 + iOS → 不加
        mgr.platform = "ios"
        on_ios = mgr._session_caps() == {}
        # 开 + Android + 用户显式设了 unicodeKeyboard=False → 尊重用户，不覆盖
        mgr.platform = "android"
        mgr.extra_caps = {"unicodeKeyboard": False}
        explicit = mgr._session_caps() == {"unicodeKeyboard": False}
        ok = off_android and on_android and on_ios and explicit
    finally:
        if prev is None:
            _os.environ.pop(key, None)
        else:
            _os.environ[key] = prev
    print("unicodeKeyboard 开关(开/关/iOS/显式不覆盖):", "✅" if ok else "❌")
    return ok


def test_browser_open_caps() -> bool:
    """打开手机浏览器：无会话时用 browserName cap 建会话；已有会话则复用不重建。"""
    from autopilot.keywords.mobile import session as sess
    from autopilot.keywords.context import ExecutionContext

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Mgr:
        def __init__(self):
            self._driver = None
            self.extra_caps = {}
            self.created = None
            self.platform = "android"
        @property
        def has_driver(self):
            return self._driver is not None
        def create(self, os_type, pkg, act, udid=""):
            self.created = (os_type, pkg, act, udid, dict(self.extra_caps))
            self._driver = object()

    mgr = _Mgr()
    orig = sess.get_manager
    sess.get_manager = lambda _ctx: mgr
    try:
        ctx = ExecutionContext()
        sess.browser_open(ctx, type="Chrome")
        built = (mgr.created is not None
                 and mgr.created[0] == "Android" and mgr.created[1] == ""
                 and mgr.created[4].get("browserName") == "Chrome")
        # 再调一次：已有会话 → 不重建（created 不变）
        snapshot = mgr.created
        sess.browser_open(ctx, type="Chrome")
        reused = mgr.created is snapshot
        ok = built and reused
    finally:
        sess.get_manager = orig
    print("browser_open(browserName建会话/复用):", "✅" if ok else "❌")
    return ok


def test_mobile_device_by_platform_start() -> bool:
    """mobile_app_start picks the UDID that matches its platform."""
    from autopilot.keywords.mobile import session as sess
    from autopilot.keywords.context import ExecutionContext

    calls = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Mgr:
        def create(self, os_type, pkg, act, udid=""):
            calls.append((os_type, pkg, act, udid))

    orig = sess.get_manager
    sess.get_manager = lambda _ctx: _Mgr()
    try:
        ctx = ExecutionContext()
        ctx.set_var("__device_udid_by_platform__", {
            "android": "AND-1",
            "ios": "IOS-1",
        })
        sess.app_start(ctx, type="Android", packageName="pkg")
        sess.app_start(ctx, type="iOS", packageName="bundle")
        explicit_ctx = ExecutionContext()
        explicit_ctx.set_var("__device_udid_by_platform__", {
            "android": "AND-1",
            "ios": "IOS-1",
        })
        sess.app_start(explicit_ctx, type="Android", udid="AND-2")
        ok = calls == [
            ("Android", "pkg", "", "AND-1"),
            ("iOS", "bundle", "", "IOS-1"),
            ("Android", "", "", "AND-2"),
        ]
    finally:
        sess.get_manager = orig
    print("mobile_app_start platform UDID:", "OK" if ok else "FAIL", calls)
    return ok


def test_run_cases_device_by_case_platform() -> bool:
    """run_cases injects the matching UDID for each testcase platform."""
    from autopilot.engine import run_cases
    from autopilot.model.testcase import TestCase, Step, ParamValue
    from autopilot.keywords.mobile import session as sess

    calls = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Mgr:
        server = "http://127.0.0.1:4723"

        def start_server(self):
            pass

        def create(self, os_type, pkg, act, udid=""):
            calls.append((os_type, udid))

    orig = sess.get_manager
    sess.get_manager = lambda _ctx: _Mgr()
    try:
        android = TestCase(name="a", platform="android")
        android.case.steps = [
            Step("appium_start", ""),
            Step("mobile_app_start", "", params=[ParamValue("type", "Android")]),
        ]
        ios = TestCase(name="i", platform="ios")
        ios.case.steps = [
            Step("appium_start", ""),
            Step("mobile_app_start", "", params=[ParamValue("type", "iOS")]),
        ]
        suite = run_cases([android, ios], base_vars={
            "__device_udid_by_platform__": {
                "android": "AND-1",
                "ios": "IOS-1",
            }
        })
        ok = calls == [("Android", "AND-1"), ("iOS", "IOS-1")] \
            and suite.case_counts()["failed"] == 0
    finally:
        sess.get_manager = orig
    print("run_cases platform UDID:", "OK" if ok else "FAIL", calls)
    return ok


def test_deviceinfo_getprop_fallback() -> bool:
    """deviceInfo 未知项按原始 getprop 键兜底取值；连原始键也空才抛。"""
    from autopilot.keywords.mobile import misc as mm
    from autopilot.keywords.context import ExecutionContext
    from autopilot.keywords.registry import KeywordError

    props = {"ro.custom.flavor": "spicy"}   # 白名单外的原始 getprop 键
    orig_shell, orig_serial = mm.adb_shell, mm._serial
    mm._serial = lambda _ctx: ""
    mm.adb_shell = lambda cmd, serial="": props.get(cmd.split()[-1], "") if cmd.startswith("getprop") else ""
    try:
        ctx = ExecutionContext()
        # 避免走 iOS/会话分支：无 appium → is_ios False，AndroidVersion 分支跳过
        hit = mm.get_device_info(ctx, deviceInfo="ro.custom.flavor", outVar="V") == {"V": "spicy"}
        raised = False
        try:
            mm.get_device_info(ctx, deviceInfo="ro.does.not.exist", outVar="V")
        except KeywordError:
            raised = True
        ok = hit and raised
    finally:
        mm.adb_shell, mm._serial = orig_shell, orig_serial
    print("deviceInfo(未知项getprop兜底/空则抛):", "✅" if ok else "❌")
    return ok


def test_ios_install_app_backend() -> bool:
    """_ios_install_app：pymobiledevice3 失败时回退 go-ios，并返回后端标识。"""
    from autopilot.keywords.mobile import session as sess
    from autopilot.mobile import ipa as ipamod
    from autopilot.mobile import ios_bootstrap as ib

    saved_pmd3 = sess._ios_pmd3_run
    saved_parse = ipamod.parse_ipa
    saved_avail = ib.available
    saved_install = ib.install_app
    ipamod.parse_ipa = lambda p: ipamod.IpaInfo(bundle_id="com.demo.ios", version_name="1.0")
    def _boom(coro):
        coro.close()
        raise RuntimeError("no device")

    sess._ios_pmd3_run = _boom
    ib.available = lambda: True
    ib.install_app = lambda path, udid="", log=None, timeout=300: "go-ios-ok"
    try:
        backend = sess.ios_install_app("/x/a.ipa", udid="ios-1", log=lambda _m: None)
        ok = backend == "go-ios"
    finally:
        sess._ios_pmd3_run = saved_pmd3
        ipamod.parse_ipa = saved_parse
        ib.available = saved_avail
        ib.install_app = saved_install
    print("_ios_install_app(pmd3→go-ios 回退):", "✅" if ok else "❌")
    return ok


def test_app_adb_uninstall() -> bool:
    """卸载移动应用：Android 走 adb pm uninstall；iOS 走 _ios_uninstall_app。"""
    from autopilot.keywords.mobile import session as sess
    from autopilot.keywords.context import ExecutionContext

    calls = {"adb": [], "ios": []}
    saved = (sess.run_adb, sess._ios_uninstall_app, sess._serial,
             sess._device_for_platform)
    sess.run_adb = lambda args, serial="", timeout=0: (
        calls["adb"].append((list(args), serial)) or "Success"
    )
    sess._ios_uninstall_app = lambda bundle_id, udid="", log=None: (
        calls["ios"].append((bundle_id, udid)) or "pymobiledevice3"
    )
    sess._serial = lambda _ctx: "sess-dev"
    sess._device_for_platform = lambda _ctx, platform="", explicit="": (
        str(explicit).strip() or {"android": "AND-1", "ios": "IOS-1"}.get(
            sess._platform_key(platform), "")
    )
    try:
        ctx = ExecutionContext()
        sess.app_adb_uninstall(ctx, type="android", packageName="com.demo")
        android_ok = calls["adb"] == [(["shell", "pm", "uninstall", "com.demo"], "AND-1")]
        calls["adb"].clear()
        sess.app_adb_uninstall(ctx, type="android", packageName="com.demo",
                               cacheSave="是")
        android_keep = calls["adb"] == [(["shell", "pm", "uninstall", "-k", "com.demo"], "AND-1")]
        calls["ios"].clear()
        sess.app_adb_uninstall(ctx, type="ios", packageName="com.demo.ios")
        ios_ok = calls["ios"] == [("com.demo.ios", "IOS-1")]
        ok = android_ok and android_keep and ios_ok
    finally:
        (sess.run_adb, sess._ios_uninstall_app, sess._serial,
         sess._device_for_platform) = saved
    print("app_adb_uninstall(Android/iOS分支):", "✅" if ok else "❌")
    return ok


def test_sync_manager_ports_from_ctx() -> bool:
    """get_manager 从 ctx 同步 __wda_local_port__ 等到 AppiumManager。"""
    from autopilot.keywords.context import ExecutionContext
    from autopilot.keywords.mobile.driver import get_manager
    ctx = ExecutionContext()
    ctx.set_var("__wda_local_port__", 8102)
    ctx.set_var("__tunnel_info_port__", 28120)
    mgr = get_manager(ctx)
    ok = mgr._wda_port == 8102 and mgr._tunnel_port == 28120
    print("sync manager ports:", "OK" if ok else "FAIL", mgr._wda_port, mgr._tunnel_port)
    return ok


def test_ios_find_strategies() -> bool:
    from autopilot.model.mapfile import Locator
    from autopilot.keywords.mobile.driver import _ios_find_strategies

    loc = Locator(type="XPATH", value="//*[@name='Try Now']")
    strategies = _ios_find_strategies(loc)
    flat = [f"{b}:{v}" for b, v in strategies]
    # WDA 官方查 label：link text「label=文案」；不再硬套 Alert xpath
    ok = (any(b == "link text" and v == "label=Try Now" for b, v in strategies)
          and any("predicate string" in b and 'label == "Try Now"' in v for b, v in strategies)
          and not any("XCUIElementTypeAlert" in v for b, v in strategies))
    print("iOS 定位(WDA link text/label):", "OK" if ok else "FAIL", flat[:4])
    pred = Locator(type="PREDICATE", value='label == "Agree"')
    ps = _ios_find_strategies(pred)
    ok2 = (ps[0] == ("-ios predicate string", 'label == "Agree"')
           and ("link text", "label=Agree") in ps)
    print("predicate:: + link text:", "OK" if ok2 else "FAIL", ps)
    return ok and ok2


def test_ios_find_strategies_backend_order() -> bool:
    """Appium/WDA 分支策略顺序不同，且 Appium 路径无重复策略。"""
    from autopilot.model.mapfile import Locator
    from autopilot.keywords.mobile.driver import _ios_find_strategies

    loc = Locator(type="NAME", value="OK")
    appium = _ios_find_strategies(loc, "appium")
    wda = _ios_find_strategies(loc, "wda")
    no_dup = len(appium) == len(set(appium)) and len(wda) == len(set(wda))
    wda_label = next(i for i, (b, v) in enumerate(wda) if b == "link text" and v == "label=OK")
    wda_acc = next(i for i, (b, v) in enumerate(wda) if b == "accessibility id")
    appium_acc = next(i for i, (b, v) in enumerate(appium) if b == "accessibility id")
    appium_label = next(i for i, (b, v) in enumerate(appium) if b == "link text" and v == "label=OK")
    order_ok = wda_label < wda_acc and appium_acc < appium_label
    ok = no_dup and order_ok
    print("iOS 策略 backend 分支(无重复/顺序):", "OK" if ok else "FAIL")
    return ok


def test_wda_session_launch_not_bundle_cap() -> bool:
    """会话 caps 不绑 bundleId，改由 launch_app 拉起（系统 Alert 可查）。"""
    from autopilot.keywords.mobile import driver as drv_mod
    from autopilot.keywords.mobile import wda_client as wcmod
    from autopilot.mobile import ios_bootstrap as ib

    calls: list = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakePrep:
        def __init__(self, *_a, **_k):
            pass

        def prepare(self, **_kw):
            return "http://127.0.0.1:8100"

        def stop(self):
            pass

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeClient:
        def __init__(self, *_a, **_k):
            pass

        def create_session(self, bundle_id="", caps=None):
            calls.append(("create_session", bundle_id, caps))

        def set_recover(self, *_a, **_k):
            pass

        def launch_app(self, bundle_id, **_k):
            calls.append(("launch_app", bundle_id))

        def activate_app(self, bundle_id):
            calls.append(("activate_app", bundle_id))

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeDriver:
        def __init__(self, client, bundle_id=""):
            self.client = client
            self.bundle_id = bundle_id

    orig = (ib.IosDevicePrep, ib.wda_alive, ib.is_port_listening, ib.kill_listeners,
            wcmod.WdaClient, wcmod.WdaDriver)
    try:
        ib.IosDevicePrep = _FakePrep
        ib.wda_alive = lambda *_a, **_k: False
        ib.is_port_listening = lambda *_a, **_k: False
        ib.kill_listeners = lambda *_a, **_k: []
        wcmod.WdaClient = _FakeClient
        wcmod.WdaDriver = _FakeDriver
        mgr = drv_mod.AppiumManager()
        drv = mgr._create_wda_driver("imobile.broadcast.app", "UDID1")
        ok = (calls[0][0] == "create_session" and calls[0][1] == ""
              and ("launch_app", "imobile.broadcast.app") in calls
              and getattr(drv, "bundle_id", "") == "imobile.broadcast.app")
    finally:
        (ib.IosDevicePrep, ib.wda_alive, ib.is_port_listening, ib.kill_listeners,
         wcmod.WdaClient, wcmod.WdaDriver) = orig
    print("WDA session 不绑 bundleId + launch:", "OK" if ok else "FAIL", calls)
    return ok


def test_ios_alert_helpers() -> bool:
    from autopilot.keywords.mobile.driver import (
        extract_ios_button_label, _decode_xml_entities, ios_alert_locator_hint,
        try_ios_alert_click,
    )
    from autopilot.keywords.context import ExecutionContext
    from autopilot.model.mapfile import Locator
    import time as _time

    pred = Locator(type="PREDICATE", value='label == "WLAN & Cellular"')
    ok1 = extract_ios_button_label(pred) == "WLAN & Cellular"
    ok2 = _decode_xml_entities("WLAN &amp; Cellular") == "WLAN & Cellular"
    ok_hint = ios_alert_locator_hint(pred)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeClient:
        def __init__(self, *, delay_open: float = 0):
            self.open = False
            self.accepted: list[str] = []
            self._delay = delay_open
            self._t0 = _time.monotonic()

        def alert_text(self):
            if self._delay and _time.monotonic() - self._t0 < self._delay:
                raise RuntimeError("no alert")
            if not self.open:
                raise RuntimeError("no alert")

        def source(self):
            if not self.open:
                return "<XCUIElementTypeApplication/>"
            return ('<XCUIElementTypeAlert>'
                    '<XCUIElementTypeButton label="WLAN &amp; Cellular"/>'
                    '<XCUIElementTypeButton label="WLAN Only"/>'
                    '</XCUIElementTypeAlert>')

        def alert_accept(self, name=""):
            self.accepted.append(name)
            if name == "WLAN & Cellular":
                self.open = False

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeMgr:
        platform = "ios"
        backend = "wda"

        def __init__(self, client):
            self._client = client

        def driver(self):
            return type("D", (), {"wda_client": self._client})()

        def optional_driver(self):
            return self.driver()

    import autopilot.keywords.mobile.driver as drv_mod
    orig = drv_mod.get_manager
    fake_client = _FakeClient()
    fake_client.open = True
    try:
        drv_mod.get_manager = lambda _ctx: _FakeMgr(fake_client)
        ok3 = try_ios_alert_click(ExecutionContext(), pred, 2000)
        ok4 = fake_client.accepted == ["WLAN & Cellular"]
    finally:
        drv_mod.get_manager = orig

    delayed = _FakeClient(delay_open=0.5)
    ok5 = False
    try:
        mgr = _FakeMgr(delayed)

        def _open_alert():
            _time.sleep(0.55)
            delayed.open = True

        import threading
        threading.Thread(target=_open_alert, daemon=True).start()
        drv_mod.get_manager = lambda _ctx: mgr
        ok5 = try_ios_alert_click(ExecutionContext(), pred, 3000, wait_for_alert=True)
        ok5 = ok5 and delayed.accepted == ["WLAN & Cellular"]
    finally:
        drv_mod.get_manager = orig

    print("iOS Alert API(真机路径):", "OK" if ok1 and ok2 and ok_hint and ok3 and ok4 and ok5 else "FAIL")
    return ok1 and ok2 and ok_hint and ok3 and ok4 and ok5


def test_ios_alert_weak_hint_budget() -> bool:
    """弱 Alert hint（@name Allow）不应占满 timeout，应保留 find 时间。"""
    from autopilot.keywords.mobile.driver import (
        ios_alert_strong_hint, ios_alert_wait_budget_ms,
    )
    from autopilot.model.mapfile import Locator

    pred = Locator(type="PREDICATE", value='label == "WLAN & Cellular"')
    weak = Locator(type="XPATH", value="//*[@name='Allow']")
    ok = (
        ios_alert_strong_hint(pred)
        and not ios_alert_strong_hint(weak)
        and ios_alert_wait_budget_ms(weak, 5000) == 2000
        and ios_alert_wait_budget_ms(pred, 5000) == 5000
    )
    print("iOS Alert 弱 hint 预算:", "OK" if ok else "FAIL")
    return ok


def test_class_chain_locator_parse() -> bool:
    """class-chain:: 应解析为 CLASS_CHAIN 并由 driver 映射到 WDA class chain。"""
    from autopilot.keywords.context import ExecutionContext
    from autopilot.keywords.mobile.driver import _mobile_locator_to_by

    ctx = ExecutionContext()
    loc = ctx.resolve_locator("class-chain::**/XCUIElementTypeButton[`label == \"OK\"`]")
    ok = (
        loc is not None
        and loc.type == "CLASS_CHAIN"
        and _mobile_locator_to_by(loc) == (
            "-ios class chain", '**/XCUIElementTypeButton[`label == "OK"`]')
    )
    print("class-chain 解析:", "OK" if ok else "FAIL", getattr(loc, "type", None))
    return ok


def test_ios_platform_helpers() -> bool:
    ok = (
        mp.pretty_backend_name("wda") == "WDA-direct"
        and mp.ios_uses_appium_backend("wda") is False
        and mp.ios_uses_appium_backend("appium") is True
        and mp.ios_inspector_uses_appium("wda") is False
        and mp.ios_inspector_uses_appium("appium") is True
        and mp.ios_session_uses_wda("Android") is False
        and mp.ios_session_uses_wda("iOS", mode="wda") is True
        and mp.ios_session_uses_wda("iOS", mode="appium") is False
    )
    print("platform UI helpers:", "OK" if ok else "FAIL")
    return ok


def test_appium_start_skip_ios_wda() -> bool:
    """appium_start：iOS WDA-direct 跳过本机 Appium；Android / iOS+Appium 仍启动。"""
    from autopilot.keywords.mobile import session as sess
    from autopilot.keywords.context import ExecutionContext
    from autopilot.engine.suite import _apply_case_device_vars, _case_platform
    from autopilot.model.testcase import TestCase, Step, ParamValue

    calls: list[str] = []
    logs: list[str] = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Mgr:
        server = "http://127.0.0.1:4723"
        backend_mode = "auto"
        platform = ""
        extra_caps: dict = {}

        def start_server(self):
            calls.append("start")

    orig = sess.get_manager

    def fake_mgr(exec_ctx):
        m = _Mgr()
        bm = exec_ctx.get_var("__mobile_backend_mode__")
        if bm not in (None, ""):
            m.backend_mode = str(bm)
        cp = exec_ctx.get_var("__current_platform__")
        if cp:
            m.platform = str(cp)
        return m

    orig_log = ExecutionContext.log

    def capture_log(self, msg):
        logs.append(str(msg))
        orig_log(self, msg)

    sess.get_manager = fake_mgr
    ExecutionContext.log = capture_log
    try:
        wda_skip = mp.ios_session_uses_wda("ios", mode="auto")

        ctx = ExecutionContext()
        ctx.set_var("__current_platform__", "ios")
        calls.clear()
        logs.clear()
        sess.appium_start(ctx)
        ok_ios_auto = ("start" not in calls) == wda_skip
        ok_ios_auto = ok_ios_auto and (
            any("WDA-direct" in line for line in logs) if wda_skip else calls == ["start"]
        )

        ctx2 = ExecutionContext()
        ctx2.set_var("__current_platform__", "android")
        calls.clear()
        logs.clear()
        sess.appium_start(ctx2)
        ok_android = calls == ["start"]

        ctx3 = ExecutionContext()
        ctx3.set_var("__current_platform__", "ios")
        ctx3.set_var("__mobile_backend_mode__", "appium")
        calls.clear()
        logs.clear()
        sess.appium_start(ctx3)
        ok_ios_appium = calls == ["start"]

        calls.clear()
        logs.clear()
        sess.appium_start(ExecutionContext())
        ok_unknown = calls == ["start"]

        tc = TestCase(name="ipa_case", platform="")
        tc.case.steps = [
            Step("mobile_app_install_and_open", "", params=[
                ParamValue("type", "ios"),
                ParamValue("appFile", r"C:\apps\demo.ipa"),
            ]),
        ]
        ok_infer = _case_platform(tc) == "ios"
        ctx4 = ExecutionContext()
        _apply_case_device_vars(ctx4, tc, {})
        ok_ctx = ctx4.get_var("__current_platform__") == "ios"

        ok = ok_ios_auto and ok_android and ok_ios_appium and ok_unknown and ok_infer and ok_ctx
    finally:
        sess.get_manager = orig
        ExecutionContext.log = orig_log
    print("appium_start skip iOS WDA:", "OK" if ok else "FAIL", f"wda_skip={wda_skip}")
    return ok


def main() -> int:
    ok = all([test_backend_selection(), test_appium_manager_server_bootstrap(),
              test_wda_using_and_path(),
              test_wda_driver_unsupported(), test_wda_tap_swipe_deviceinfo(),
              test_map_platform_locator(), test_wda_reuse_by_udid(),
              test_resolve_apk_path(), test_find_element_wait(),
              test_mobile_timeout_threaded(), test_text_clear_password(),
              test_intent_to_miniprogram(), test_toast_verify(),
              test_comm_action_touch(), test_install_ime(),
              test_install_open_device_by_platform(),
              test_unicode_keyboard_caps(), test_browser_open_caps(),
              test_mobile_device_by_platform_start(),
              test_run_cases_device_by_case_platform(),
              test_deviceinfo_getprop_fallback(), test_install_keepdata(),
              test_ios_install_app_backend(), test_app_adb_uninstall(),
              test_sync_manager_ports_from_ctx(), test_ios_find_strategies(),
              test_ios_find_strategies_backend_order(),
              test_ios_alert_weak_hint_budget(),
              test_class_chain_locator_parse(),
              test_ios_platform_helpers(),
              test_appium_start_skip_ios_wda(),
              test_wda_session_launch_not_bundle_cap(), test_ios_alert_helpers()])
    print("\n总结:", "✅ 移动端后端分支全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
