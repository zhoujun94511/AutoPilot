"""真实 headless Chrome 验证（可选，需本机有 Chrome）。
独立于 test_web.py（后者用 FakeDriver，无需浏览器）。
"""

import os
import sys
import pathlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.keywords.context import ExecutionContext
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy

HTML = """<!doctype html><html><head><title>AutoPilot Real</title></head>
<body><h1 id="t">Hello AutoPilot</h1>
<input id="username"><button id="login">Login</button></body></html>"""


def main() -> int:
    tmp = pathlib.Path(os.environ.get("TEMP", ".")) / "ap_real_test.html"
    tmp.write_text(HTML, encoding="utf-8")
    url = tmp.as_uri()  # file:///C:/...
    print("URL:", url)

    ctx = ExecutionContext()
    tc = TestCase(name="real")
    tc.case.steps = [
        Step("web_browser_open", "打开", params=[
            ParamValue("url", url), ParamValue("type", "Headless")]),
        Step("web_element_text_input", "输入", params=[
            ParamValue("locator", "id::username"), ParamValue("text", "admin"),
            ParamValue("isClear", "是")]),
        Step("web_element_click", "点击", params=[
            ParamValue("locator", "id::login"), ParamValue("isScroll", "是"),
            ParamValue("scrollMode", "")]),
        Step("web_element_get_element_text", "取h1", params=[
            ParamValue("locator", "id::t"), ParamValue("outVar", "h1")]),
        Step("web_browser_getBrowserTitle", "取标题", params=[ParamValue("title", "tt")]),
        Step("web_browser_quit", "退出", params=[]),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.STOP).run_testcase(tc)
    for r in res.results:
        print(f"  [{r.status}] {r.keyword_id} {r.message}")
    print("h1=", repr(ctx.get_var("h1")), "| title=", repr(ctx.get_var("tt")),
          "| counts=", res.counts())
    ok = ctx.get_var("h1") == "Hello AutoPilot" and ctx.get_var("tt") == "AutoPilot Real"
    print("真实 Chrome 验证:", "✅" if ok else "❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
