"""iOS 组件层回归（离线，不依赖 selenium）。"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class _FakeWdaClient:
    """最小 WDA client 桩，供组件测试。"""

    session_id = "S1"

    def __init__(self, bundle_id: str = "com.test.app"):
        self.bundle_id = bundle_id
        self.posts = []
        self._ctx = "NATIVE_APP"

    def terminate_app(self, bundle_id: str) -> None:
        self.posts.append(("/wda/apps/terminate", {"bundleId": bundle_id}))

    def activate_app(self, bundle_id: str) -> None:
        self.posts.append(("/wda/apps/activate", {"bundleId": bundle_id}))

    def app_state(self, _bundle_id: str) -> int:
        return 4

    def list_contexts(self) -> list[str]:
        return ["NATIVE_APP", "WEBVIEW_1"]

    def get_context(self) -> str:
        return self._ctx

    def set_context(self, name: str) -> None:
        self._ctx = name

    def press_button(self, name: str) -> None:
        self.posts.append(("/wda/pressButton", {"name": name}))

    def press_delete(self, count: int = 1) -> None:
        n = max(1, int(count or 1))
        for _ in range(n):
            self.posts.append(("/wda/keys", {"value": ["\ue003"]}))


class _FakeWdaDriver:
    def __init__(self, client: _FakeWdaClient):
        self._c = client
        self._bundle_id = client.bundle_id
        self.capabilities = {"platformName": "iOS", "automationName": "WDA-Direct",
                             "bundleId": self._bundle_id}
        # noinspection PyProtectedMember
        self._ctx = client._ctx

    def set_context(self, name: str) -> None:
        self._c.set_context(name)
        self._ctx = name

    def get_context(self) -> str:
        return self._c.get_context()

    def terminate_app(self, bundle_id: str = "") -> None:
        self._c.terminate_app(bundle_id or self._bundle_id)

    def activate_app(self, bundle_id: str = "") -> None:
        self._c.activate_app(bundle_id or self._bundle_id)

    def is_app_installed(self, bundle_id: str = "") -> bool:
        return self._c.app_state(bundle_id or self._bundle_id) >= 1

    @property
    def current_package(self) -> str:
        return self._bundle_id

    @property
    def contexts(self) -> list[str]:
        return self._c.list_contexts()

    @property
    def switch_to(self):
        return self

    @property
    def context(self) -> str:
        return self._c.get_context()

    @context.setter
    def context(self, name: str) -> None:
        self._c.set_context(name)

    def press_button(self, name: str) -> None:
        self._c.press_button(name)

    def press_delete(self, count: int = 1) -> None:
        self._c.press_delete(count)

    @staticmethod
    def device_info() -> dict:
        return {"ip": "192.168.1.88", "version": "17.0"}


def test_wda_lifecycle_api() -> bool:
    client = _FakeWdaClient()
    drv = _FakeWdaDriver(client)
    drv.terminate_app()
    drv.activate_app()
    ok = (
        client.posts[0] == ("/wda/apps/terminate", {"bundleId": "com.test.app"})
        and client.posts[1] == ("/wda/apps/activate", {"bundleId": "com.test.app"})
        and drv.is_app_installed()
        and drv.current_package == "com.test.app"
    )
    print("WDA lifecycle API:", "OK" if ok else "FAIL", client.posts[:2])
    return ok


def test_wda_context_api() -> bool:
    drv = _FakeWdaDriver(_FakeWdaClient("x"))
    ok = drv.contexts == ["NATIVE_APP", "WEBVIEW_1"]
    drv.switch_to.context = "WEBVIEW_1"
    ok = ok and drv.context == "WEBVIEW_1"
    print("WDA context API:", "OK" if ok else "FAIL")
    return ok


def test_ios_lifecycle_component() -> bool:
    from autopilot.mobile.ios.app_lifecycle import reset_app, current_bundle_id
    from autopilot.keywords.registry import KeywordError

    client = _FakeWdaClient("com.a")
    drv = _FakeWdaDriver(client)
    reset_app(drv, "wda")
    ok = (
        client.posts == [
            ("/wda/apps/terminate", {"bundleId": "com.a"}),
            ("/wda/apps/activate", {"bundleId": "com.a"}),
        ]
        and current_bundle_id(drv, "wda") == "com.a"
    )
    print("ios lifecycle component:", "OK" if ok else "FAIL", client.posts)
    # WDA 无 bundle 时不应落到 driver.reset()
    empty = _FakeWdaDriver(_FakeWdaClient(""))
    empty._bundle_id = ""
    try:
        reset_app(empty, "wda")
        print("ios lifecycle no-bundle:", "FAIL (expected KeywordError)")
        return False
    except KeywordError as e:
        ok2 = "bundleId" in str(e)
        print("ios lifecycle no-bundle:", "OK" if ok2 else "FAIL", str(e)[:80])
    from autopilot.keywords.context import ExecutionContext
    ctx = ExecutionContext()
    ctx.set_var("app_package", "com.from.ctx")
    empty2 = _FakeWdaDriver(_FakeWdaClient(""))
    empty2._bundle_id = ""
    client2 = empty2._c
    client2.posts.clear()
    reset_app(empty2, "wda", ctx=ctx)
    ok3 = client2.posts == [
        ("/wda/apps/terminate", {"bundleId": "com.from.ctx"}),
        ("/wda/apps/activate", {"bundleId": "com.from.ctx"}),
    ]
    print("ios lifecycle ctx bundle:", "OK" if ok3 else "FAIL", client2.posts)
    return ok and ok2 and ok3


def test_ios_press_delete_keys() -> bool:
    from autopilot.mobile.ios.keys import press_delete_keys

    client = _FakeWdaClient()
    drv = _FakeWdaDriver(client)
    press_delete_keys(drv, "wda", 3)
    ok = client.posts == [("/wda/keys", {"value": ["\ue003"]})] * 3
    print("ios press delete keys:", "OK" if ok else "FAIL")
    return ok


def test_ios_get_device_ip() -> bool:
    from autopilot.keywords.context import ExecutionContext
    from autopilot.keywords.mobile.driver import AppiumManager
    from autopilot.keywords.mobile.session import get_device_ip

    ctx = ExecutionContext()
    mgr = AppiumManager()
    mgr.platform = "ios"
    mgr.backend = "wda"
    drv = _FakeWdaDriver(_FakeWdaClient())
    mgr._driver = drv
    ctx.appium = mgr
    out = get_device_ip(ctx, outVar="ip")
    ok = out.get("ip") == "192.168.1.88"
    print("ios get device ip:", "OK" if ok else "FAIL", out)
    return ok


def test_ios_context_component() -> bool:
    from autopilot.mobile.ios.context_switch import switch_context

    client = _FakeWdaClient("x")
    client.list_contexts = lambda: ["NATIVE_APP", "WEBVIEW_com.app"]
    drv = _FakeWdaDriver(client)
    chosen = switch_context(drv, "wda", "WEB")
    ok = chosen == "WEBVIEW_com.app" and drv.get_context() == "WEBVIEW_com.app"
    print("ios context component:", "OK" if ok else "FAIL", chosen)
    return ok


def test_ios_keys_wda() -> bool:
    from autopilot.mobile.ios.keys import press_physical_key

    client = _FakeWdaClient()
    drv = _FakeWdaDriver(client)
    press_physical_key(drv, "wda", "home", count=2, pause_sec=0)
    ok = client.posts == [
        ("/wda/pressButton", {"name": "home"}),
        ("/wda/pressButton", {"name": "home"}),
    ]
    print("ios keys wda:", "OK" if ok else "FAIL")
    return ok


def test_session_recovery_retry() -> bool:
    from autopilot.mobile.ios.session_recovery import SessionRecovery, is_session_lost_error

    recovered = []
    r = SessionRecovery(recover=lambda: recovered.append(1))
    ok = is_session_lost_error("invalid session id")
    ok = ok and r.maybe_recover(Exception("WDA session 失效: invalid session id"))
    ok = ok and recovered == [1]
    ok = ok and not r.maybe_recover(ValueError("other"))
    print("session recovery:", "OK" if ok else "FAIL")
    return ok


def test_ios_webview_url() -> bool:
    from autopilot.mobile.ios.webview import get_current_url

    class _D:
        current_url = "https://example.com"

        @staticmethod
        def execute_script(*_a, **_k):
            return "https://fallback.com"

    ok = get_current_url(_D(), "wda") == "https://example.com"
    print("ios webview url:", "OK" if ok else "FAIL")
    return ok


def test_ios_webview_js_click_fallback() -> bool:
    from autopilot.mobile.ios.webview import js_click_element

    clicked = []

    class _El:
        @staticmethod
        def click():
            clicked.append(1)

    class _D:
        def execute_script(self, *_a, **_k):
            raise RuntimeError("no js")

    js_click_element(_D(), "wda", _El())
    ok = clicked == [1]
    print("ios webview js fallback:", "OK" if ok else "FAIL")
    return ok


def test_ensure_wda_session_hook() -> bool:
    from autopilot.mobile.ios.health import ensure_wda_session

    calls = []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Client:
        session_id = "S1"

        def ping(self):
            calls.append("ping")

        def recreate_session(self):
            calls.append("recreate")

        def launch_app(self, _bid):
            calls.append("launch")

    c = _Client()
    ensure_wda_session(c, bundle_id="com.app")
    ok = calls == ["ping"]
    c.session_id = None

    def _fail_ping():
        raise Exception("invalid session id")

    c.ping = _fail_ping
    ensure_wda_session(c, bundle_id="com.app")
    ok = ok and calls == ["ping", "recreate", "launch"]
    print("ensure_wda_session:", "OK" if ok else "FAIL", calls)
    return ok


def test_ios_swipe_strategies() -> bool:
    """iOS WDA 滑屏：ScrollView swipe > dragFromToForDuration > W3C。"""
    from autopilot.mobile.ios.swipe import wda_swipe_by_ratio

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _El:
        def __init__(self, eid: str, w: int = 390, h: int = 844):
            self.id = eid
            self._rect = {"width": w, "height": h, "x": 0, "y": 0}

        def is_displayed(self):
            return True

        @property
        def rect(self):
            return self._rect

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Client:
        def __init__(self, scroll_ok: bool = True):
            self.calls: list[tuple] = []
            self._scroll_ok = scroll_ok

        def find_elements(self, _by, value):
            if "ScrollView" in value and self._scroll_ok:
                return [_El("scroll-1")]
            return []

        def element_swipe(self, eid, direction):
            self.calls.append(("element_swipe", eid, direction))

        def drag_from_to_for_duration(self, fx, fy, tx, ty, press_duration_s=0.01):
            self.calls.append(("drag", fx, fy, tx, ty, press_duration_s))

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Drv:
        def __init__(self, client: _Client):
            self.wda_client = client
            self.w3c = []

        def get_window_size(self):
            return {"width": 390, "height": 844}

        def swipe(self, fx, fy, tx, ty, ms):
            self.w3c.append((fx, fy, tx, ty, ms))

    c1 = _Client(scroll_ok=True)
    d1 = _Drv(c1)
    s1 = wda_swipe_by_ratio(d1, "左", 0.5, 0.5, 0.5, 1000)
    ok1 = s1 == "scrollview" and c1.calls == [("element_swipe", "scroll-1", "left")]

    c2 = _Client(scroll_ok=False)
    d2 = _Drv(c2)
    s2 = wda_swipe_by_ratio(d2, "左", 0.5, 0.5, 0.5, 1000)
    ok2 = s2 == "xctest" and bool(c2.calls) and c2.calls[0][0] == "drag"

    c3 = _Client(scroll_ok=False)
    c3.drag_from_to_for_duration = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no drag"))
    d3 = _Drv(c3)
    s3 = wda_swipe_by_ratio(d3, "左", 0.5, 0.5, 0.5, 1000)
    ok3 = s3 == "w3c" and len(d3.w3c) == 1

    c4 = _Client(scroll_ok=False)
    d4 = _Drv(c4)
    s4 = wda_swipe_by_ratio(d4, "左", 0.5, 0.5, 0.5, 1000, strategy="xctest")
    ok4 = s4 == "xctest" and bool(c4.calls) and c4.calls[0][0] == "drag"

    ok = bool(ok1 and ok2 and ok3 and ok4)
    print("ios swipe strategies:", "OK" if ok else "FAIL", s1, s2, s3)
    return ok


def test_parity_skeleton() -> bool:
    from tests.ios_parity_skeleton import (
        infra_parity_case_ids,
        validate_parity_skeleton,
        parity_case_ids,
    )

    infra = infra_parity_case_ids()
    ok = (
        validate_parity_skeleton()
        and len(parity_case_ids()) >= 7
        and len(infra) >= 3
        and "ios-session-infra" in infra
    )
    print("ios parity skeleton:", "OK" if ok else "FAIL", parity_case_ids(), "infra=", infra)
    return ok


def main() -> int:
    ok = all([
        test_wda_lifecycle_api(),
        test_wda_context_api(),
        test_ios_lifecycle_component(),
        test_ios_context_component(),
        test_ios_keys_wda(),
        test_ios_press_delete_keys(),
        test_ios_get_device_ip(),
        test_session_recovery_retry(),
        test_ios_webview_url(),
        test_ios_webview_js_click_fallback(),
        test_ensure_wda_session_hook(),
        test_ios_swipe_strategies(),
        test_parity_skeleton(),
    ])
    print("\n总结:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
