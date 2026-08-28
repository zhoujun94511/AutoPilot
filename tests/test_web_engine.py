"""E1：web_engine 解析与 ROLE 定位降级 / Playwright 适配表面。"""

from __future__ import annotations

import autopilot.keywords.web.driver as web_driver_mod
from autopilot.keywords.web.driver import (
    locator_to_by,
    make_driver_factory,
    require_selenium_feature,
    resolve_web_engine,
)
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.registry import KeywordError
from autopilot.model.mapfile import Locator
from autopilot.runner.contract import JobOut, JobStatus

# Playwright 适配层（测试白盒，经 getattr 延迟解析）
def _playwright_driver_adapter(*args, **kwargs):
    cls = getattr(web_driver_mod, "_PlaywrightDriverAdapter")
    return cls(*args, **kwargs)


def _pw_element(*args, **kwargs):
    cls = getattr(web_driver_mod, "_PwElement")
    return cls(*args, **kwargs)


def test_resolve_web_engine_default(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_WEB_ENGINE", raising=False)
    monkeypatch.setattr(
        "autopilot.runtime.settings.web_engine", lambda: "selenium"
    )
    ctx = ExecutionContext()
    assert resolve_web_engine(ctx) == "selenium"


def test_resolve_web_engine_settings_fallback(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_WEB_ENGINE", raising=False)
    monkeypatch.setattr(
        "autopilot.runtime.settings.web_engine", lambda: "playwright"
    )
    ctx = ExecutionContext()
    assert resolve_web_engine(ctx) == "playwright"
    assert resolve_web_engine(None) == "playwright"


def test_resolve_web_engine_env_overrides_settings(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_WEB_ENGINE", "selenium")
    monkeypatch.setattr(
        "autopilot.runtime.settings.web_engine", lambda: "playwright"
    )
    assert resolve_web_engine(None) == "selenium"


def test_resolve_web_engine_ctx_overrides_env(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_WEB_ENGINE", "selenium")
    ctx = ExecutionContext()
    ctx.set_var("__web_engine__", "playwright")
    assert resolve_web_engine(ctx) == "playwright"


def test_role_locator_to_css():
    by, value = locator_to_by(Locator(type="ROLE", value="button"))
    assert by == "css selector"
    assert value == '[role="button"]'


def test_make_driver_factory_playwright_import_error_message():
    factory = make_driver_factory("playwright")
    try:
        import playwright  # noqa: F401

        _ = playwright
    except ImportError:
        try:
            factory("chrome")
            assert False, "expected KeywordError"
        except Exception as exc:
            assert "playwright" in str(exc).lower()


class _FakePage:
    def __init__(self):
        self.url = "https://example.com"
        self._content = "<html/>"
        self._png = b"\x89PNG"
        self.keyboard = _FakeKeyboard()
        self.mouse = _FakeMouse()

    def goto(self, url):
        self.url = url

    @staticmethod
    def title():
        return "t"

    def content(self):
        return self._content

    def screenshot(self, **kw):
        if kw.get("path"):
            open(kw["path"], "wb").write(self._png)
        return self._png

    @staticmethod
    def on(*_a, **_k):
        return None

    @staticmethod
    def set_viewport_size(*_a, **_k):
        return None

    @staticmethod
    def evaluate(*_a, **_k):
        return None


class _FakeKeyboard:
    def __init__(self):
        self.ops: list[tuple] = []

    def down(self, key):
        self.ops.append(("down", key))

    def up(self, key):
        self.ops.append(("up", key))

    def press(self, key):
        self.ops.append(("press", key))

    def type(self, text):
        self.ops.append(("type", text))


class _FakeMouse:
    def __init__(self):
        self.ops: list[tuple] = []

    def move(self, x, y, steps=1):
        self.ops.append(("move", x, y, steps))

    def down(self):
        self.ops.append(("down",))

    def up(self):
        self.ops.append(("up",))


class _FakeContext:
    def __init__(self, page):
        self.pages = [page]
        self._cookies = []

    def cookies(self):
        return list(self._cookies)

    def add_cookies(self, cookies):
        self._cookies.extend(cookies)

    def clear_cookies(self):
        self._cookies.clear()

    @staticmethod
    def close():
        return None


class _FakeBrowser:
    @staticmethod
    def close():
        return None


class _FakePw:
    @staticmethod
    def stop():
        return None


def test_pw_adapter_screenshot_and_cookies(tmp_path):
    page = _FakePage()
    ctx = _FakeContext(page)
    adapter = _playwright_driver_adapter(_FakePw(), _FakeBrowser(), ctx, page)
    assert adapter.get_screenshot_as_png() == b"\x89PNG"
    path = tmp_path / "s.png"
    assert adapter.save_screenshot(str(path))
    assert path.read_bytes() == b"\x89PNG"
    assert adapter.page_source == "<html/>"
    adapter.add_cookie({"name": "a", "value": "1", "url": "https://example.com"})
    assert adapter.get_cookie("a")["value"] == "1"
    adapter.delete_all_cookies()
    assert adapter.get_cookies() == []


def test_require_selenium_feature_blocks_playwright():
    ctx = ExecutionContext()
    ctx.set_var("__web_engine__", "playwright")
    from autopilot.keywords.web.driver import BrowserManager

    mgr = BrowserManager()
    mgr.engine = "playwright"
    ctx.web = mgr
    try:
        require_selenium_feature(ctx, "未映射能力")
        assert False, "expected KeywordError"
    except KeywordError as exc:
        assert "playwright" in str(exc).lower()


def test_pw_element_surface():
    class H:
        def __init__(self):
            self.clicked = False
            self.click_kw: dict = {}
            self.dbl = False
            self.hovered = False
            self.dragged_to = None
            self.sel: dict = {}
            self.v = ""
            self.typed = ""
            self.focused = False

        def click(self, **kw):
            self.clicked = True
            self.click_kw = kw

        def dblclick(self):
            self.dbl = True

        def hover(self):
            self.hovered = True

        def drag_to(self, other):
            self.dragged_to = other

        def select_option(self, **kw):
            self.sel = kw

        def fill(self, v):
            self.v = v

        def type(self, v):
            self.typed = v

        @staticmethod
        def inner_text():
            return "hi"

        @staticmethod
        def get_attribute(n):
            return "x" if n == "id" else None

        @staticmethod
        def is_visible():
            return True

        @staticmethod
        def is_enabled():
            return True

        @staticmethod
        def is_checked():
            return False

        @staticmethod
        def evaluate(script, *_a, **_k):
            if "selectedOptions" in str(script):
                return ["A", "B"]
            return None

        @staticmethod
        def bounding_box():
            return {"x": 10, "y": 20, "width": 40, "height": 10}

        def focus(self):
            self.focused = True

    page = _FakePage()
    el = _pw_element(H(), page)
    el.click()
    el.context_click()
    assert el.handle.click_kw.get("button") == "right"
    el.double_click()
    assert el.handle.dbl is True
    el.hover()
    assert el.handle.hovered is True
    tgt = _pw_element(H(), page)
    el.drag_to(tgt)
    assert el.handle.dragged_to is tgt.handle
    el.select_option(label="x")
    assert el.handle.sel == {"label": "x"}
    assert el.selected_option_texts() == ["A", "B"]
    el.clear()
    el.send_keys("ab")
    assert el.text == "hi"
    assert el.get_attribute("id") == "x"
    assert el.is_displayed() is True


def test_pw_combo_and_gestures_keywords(monkeypatch):
    from autopilot.keywords.web import element as el_mod
    from autopilot.keywords.web.driver import BrowserManager

    page = _FakePage()

    class H:
        def __init__(self):
            self.ops = []

        def click(self, **kw):
            self.ops.append(("click", kw))

        def dblclick(self):
            self.ops.append(("dbl",))

        def hover(self):
            self.ops.append(("hover",))

        def drag_to(self, other):
            self.ops.append(("drag", other))

        def select_option(self, **kw):
            self.ops.append(("select", kw))

        @staticmethod
        def bounding_box():
            return {"x": 0, "y": 0, "width": 20, "height": 20}

        def focus(self):
            self.ops.append(("focus",))

        @staticmethod
        def evaluate(*_a, **_k):
            return ["选中"]

    handle = H()
    pw_el = _pw_element(handle, page)
    tgt = _pw_element(H(), page)

    ctx = ExecutionContext()
    mgr = BrowserManager()
    mgr.engine = "playwright"
    ctx.web = mgr

    monkeypatch.setattr(el_mod, "find_element", lambda *_a, **_k: pw_el)
    monkeypatch.setattr(el_mod.time, "sleep", lambda *_: None)

    el_mod.combo_select(ctx, locator=None, type="文本", value="foo")
    assert ("select", {"label": "foo"}) in handle.ops
    el_mod.element_context_click(ctx, locator=None)
    el_mod.element_double_click(ctx, locator=None)
    el_mod.element_move(ctx, locator=None)

    calls = {"n": 0}

    def _fe(_ctx, _loc=None, **_kw):
        calls["n"] += 1
        return pw_el if calls["n"] == 1 else tgt

    monkeypatch.setattr(el_mod, "find_element", _fe)
    el_mod.element_drag(ctx, source=None, target=None)
    assert any(op[0] == "drag" for op in handle.ops)

    monkeypatch.setattr(el_mod, "find_element", lambda *_a, **_k: pw_el)
    el_mod.puzzle_drag_by_offset(ctx, locator=None, xOffset="100", yOffset="0")
    assert any(op[0] == "move" for op in page.mouse.ops)
    el_mod.element_drag_by_offset_for_login(
        ctx, source=None, xOffset="50", yOffset="0"
    )
    el_mod.key_press_with_selenium(
        ctx, locator=None, modifierkey="Ctrl", key="a", count="1"
    )
    assert ("down", "Control") in page.keyboard.ops


def test_job_out_web_engine_and_resolve():
    job = JobOut.from_dict(
        {
            "id": "j1",
            "name": "t",
            "status": JobStatus.PENDING.value,
            "platform": "web",
            "backend_mode": "chrome",
            "web_engine": "playwright",
        }
    )
    assert job.web_engine == "playwright"
    ctx = ExecutionContext()
    ctx.set_var("__web_engine__", job.web_engine)
    ctx.set_var("__web_browser__", "chrome")
    assert resolve_web_engine(ctx) == "playwright"


def test_find_element_selenium_not_found_wraps_keyword_error(monkeypatch):
    from autopilot.keywords.web.driver import BrowserManager, find_element

    class _FakeDriver:
        @staticmethod
        def find_element(by, value):
            from selenium.common.exceptions import NoSuchElementException

            raise NoSuchElementException(f"no such element: {by}={value}")

    ctx = ExecutionContext()
    mgr = BrowserManager()
    mgr.engine = "selenium"
    ctx.web = mgr
    monkeypatch.setattr(mgr, "driver", lambda: _FakeDriver())

    try:
        find_element(ctx, Locator(type="ID", value="missing"))
        assert False, "expected KeywordError"
    except KeywordError as exc:
        assert "未找到元素" in str(exc)
        assert "missing" in str(exc)


def test_switch_frame_selenium_not_frame_wraps_keyword_error(monkeypatch):
    from autopilot.keywords.web import browser as br_mod
    from autopilot.keywords.web.driver import BrowserManager

    class _FakeSwitchTo:
        @staticmethod
        def frame(_el):
            from selenium.common.exceptions import WebDriverException

            raise WebDriverException("element is not a iframe")

    class _FakeDriver:
        switch_to = _FakeSwitchTo()

    ctx = ExecutionContext()
    mgr = BrowserManager()
    mgr.engine = "selenium"
    ctx.web = mgr
    monkeypatch.setattr(mgr, "driver", lambda: _FakeDriver())
    monkeypatch.setattr(
        br_mod, "find_element", lambda *_a, **_k: object()
    )

    try:
        br_mod.browser_switch_frame(ctx, locator=Locator(type="ID", value="btn"))
        assert False, "expected KeywordError"
    except KeywordError as exc:
        assert "不是 frame" in str(exc)


def test_probe_host_capabilities_web_playwright_flag(monkeypatch):
    from autopilot.mgmt import local_devices as ld

    monkeypatch.setattr(ld, "_has_web_browser", lambda: True)
    monkeypatch.setattr(ld, "_has_playwright", lambda: True)
    monkeypatch.setattr(ld, "_host_backends", lambda: [])
    caps, backends = ld.probe_host_capabilities()
    assert "web" in caps
    assert "http" in caps
    assert "web-playwright" in caps
    assert backends == []


def test_run_base_vars_skips_web_engine_without_web_platform(monkeypatch):
    import tempfile
    from unittest.mock import patch

    from autopilot.model.testcase import TestCase
    from autopilot.ui.main_window import MainWindow

    from tests._qt import get_qt_app

    get_qt_app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = (["fake-android"], [])
        win._web_engine = "playwright"
        win._inspect_browser = "chrome"
        with patch.object(win, "_target_platforms", return_value={"android"}):
            base = win._run_base_vars(
                [TestCase(name="a", platform="android")],
                skip_device_pick=True,
            )
        win.close()
    assert base is not None
    assert "__web_engine__" not in base
    assert "__web_browser__" not in base
