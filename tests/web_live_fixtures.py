"""Web live 测试 fixtures（parametrize selenium | playwright）。"""

from __future__ import annotations

import pytest

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.web import browser as br_mod
from autopilot.keywords.web.driver import get_manager

from tests.web_live_support import open_live_ctx


def _selenium_available() -> bool:
    try:
        from selenium import webdriver
    except ImportError:
        return False
    try:
        from selenium.common.exceptions import WebDriverException

        opts = webdriver.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        d = webdriver.Chrome(options=opts)
        d.quit()
        return True
    except (OSError, WebDriverException):
        return False


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        from playwright.sync_api import Error as PlaywrightError

        p = sync_playwright().start()
        try:
            b = p.chromium.launch(headless=True)
            b.close()
        finally:
            p.stop()
        return True
    except (OSError, PlaywrightError):
        return False


def available_engines() -> list[str]:
    out: list[str] = []
    if _selenium_available():
        out.append("selenium")
    if _playwright_available():
        out.append("playwright")
    return out


pytestmark = pytest.mark.skipif(
    not available_engines(),
    reason="selenium / playwright 均不可用",
)


@pytest.fixture(params=available_engines())
def engine(request):
    return request.param


@pytest.fixture()
def live_ctx(http_origin, engine):
    ctx = open_live_ctx(http_origin, engine)
    try:
        yield ctx
    finally:
        get_manager(ctx).quit_all()


def engine_name(ctx: ExecutionContext) -> str:
    return getattr(get_manager(ctx), "engine", "selenium")


def confirm_ok(ctx: ExecutionContext, engine: str) -> None:
    from tests.web_live_support import elem_id
    from autopilot.keywords.web import element as el_mod

    el_mod.element_click(ctx, locator=elem_id("btn-confirm"), isScroll="否")
    if engine == "selenium":
        br_mod.browser_click_alert(ctx, isAccept="true")


def confirm_cancel(ctx: ExecutionContext, engine: str) -> None:
    from tests.web_live_support import elem_id
    from autopilot.keywords.web import element as el_mod

    if engine == "playwright":
        br_mod.browser_click_alert(ctx, isAccept="false")
    el_mod.element_click(ctx, locator=elem_id("btn-confirm"), isScroll="否")
    if engine == "selenium":
        br_mod.browser_click_alert(ctx, isAccept="false")


def prompt_with_value(ctx: ExecutionContext, engine: str, value: str) -> None:
    from tests.web_live_support import elem_id
    from autopilot.keywords.web import element as el_mod

    if engine == "playwright":
        br_mod.browser_set_prompt_value(ctx, inputValue=value)
        el_mod.element_click(ctx, locator=elem_id("btn-prompt"), isScroll="否")
        return
    el_mod.element_click(ctx, locator=elem_id("btn-prompt"), isScroll="否")
    br_mod.browser_set_prompt_value(ctx, inputValue=value)
    br_mod.browser_click_alert(ctx, isAccept="true")


def browser_type_matches(engine: str, raw: str) -> bool:
    s = str(raw or "").lower()
    if engine == "playwright":
        return "playwright" in s or "chromium" in s
    return "chrome" in s or "chromium" in s or "google" in s
