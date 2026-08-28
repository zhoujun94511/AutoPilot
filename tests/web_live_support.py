"""Web 真浏览器白盒共用夹具（Playwright / Selenium live 测试）。"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.web import browser as br_mod
from autopilot.keywords.web.driver import get_manager
from autopilot.model.mapfile import Locator

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SUITE = FIXTURE_DIR / "web_pw_suite.html"
MARK_PNG = FIXTURE_DIR / "pw_mark.png"


def css(value: str) -> Locator:
    return Locator(type="CSS", value=value)


def elem_id(value: str) -> Locator:
    return Locator(type="ID", value=value)


@pytest.fixture(scope="module")
def http_origin():
    """file:// 对 cookie / 部分导航不友好；用本机 HTTP 提供夹具。"""
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def open_live_ctx(http_origin: str, engine: str) -> ExecutionContext:
    assert SUITE.is_file()
    ctx = ExecutionContext()
    ctx.set_var("__web_engine__", engine)
    mgr = get_manager(ctx)
    assert mgr.engine == engine
    mgr.open("", "headless")
    br_mod.browser_locate(ctx, url=f"{http_origin}/web_pw_suite.html")
    return ctx


def driver(ctx: ExecutionContext):
    return get_manager(ctx).driver()


def page_events(ctx: ExecutionContext) -> dict:
    drv = driver(ctx)
    if hasattr(drv, "page"):
        return dict(drv.page.evaluate("() => window.__events || {}") or {})
    return dict(drv.execute_script("return window.__events || {}") or {})


def page_js(ctx: ExecutionContext, script: str):
    drv = driver(ctx)
    if hasattr(drv, "page"):
        return drv.page.evaluate(script)
    body = script.strip()
    if body.startswith("() =>"):
        body = body[4:].strip()
        if body.startswith("{"):
            body = body[1:]
        if body.endswith("}"):
            body = body[:-1]
    if not body.startswith("return "):
        body = "return " + body
    return drv.execute_script(body)
