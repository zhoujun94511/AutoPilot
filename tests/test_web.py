"""阶段3 WebUI 关键字测试（FakeDriver，无需真实浏览器）。

验证：浏览器打开、点击、输入、获取文本/URL/标题、元素存在、locator→By 转换、OUT 变量回写。
真实浏览器作为额外可选验证（见文末注释）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.web.driver import get_manager, locator_to_by
from autopilot.model.mapfile import Locator
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy


# ---- Fake Selenium ----

# noinspection PyMethodMayBeStatic,PyUnusedLocal
class FakeElement:
    def __init__(self, text="hello", attrs=None):
        self.text = text
        self._attrs = attrs or {}
        self.clicked = False
        self.cleared = False
        self.typed = ""

    def click(self):
        self.clicked = True

    def clear(self):
        self.cleared = True

    def send_keys(self, t):
        self.typed += str(t)

    def get_attribute(self, name):
        return self._attrs.get(name, "")


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class FakeDriver:
    def __init__(self):
        self.current_url = ""
        self.title = "Fake Title"
        self.last_find = None
        self._elements = {}
        self.quit_called = False
        self.scripts: list[str] = []

    def get(self, url):
        self.current_url = url

    def find_element(self, by, value):
        self.last_find = (by, value)
        return self._elements.setdefault((by, value), FakeElement(text=f"text@{value}"))

    def execute_script(self, script="", *a, **k):
        self.scripts.append(script)
        return None

    def back(self): self.current_url += "#back"
    def forward(self): pass
    def refresh(self): pass
    def maximize_window(self): pass
    def quit(self): self.quit_called = True


def test_locator_mapping() -> bool:
    _by, val = locator_to_by(Locator("ID", "user"))
    _by2, val2 = locator_to_by(Locator("XPATH", "//a"))
    _by3, val3 = locator_to_by(Locator("AND", tag="input",
                                       properties=[{"name": "type", "value": "text"}]))
    ok = (val == "user") and (val2 == "//a") and ("input" in val3 and "@type='text'" in val3)
    print("locator→By 映射:", "✅" if ok else "❌", f"(AND→{val3})")
    return ok


def test_web_flow() -> bool:
    ctx = ExecutionContext()
    fake = FakeDriver()
    get_manager(ctx).driver_factory = lambda _bt, _ua="": fake  # 注入假驱动
    fake._elements[("id", "link")] = FakeElement(attrs={"href": "/home"})  # 供取属性用

    tc = TestCase(name="web_demo")
    tc.case.steps = [
        Step("web_browser_open", "打开", params=[
            ParamValue("url", "www.example.com"), ParamValue("type", "Headless")]),
        Step("web_element_text_input", "输入用户名", params=[
            ParamValue("locator", "id::username"), ParamValue("text", "admin"),
            ParamValue("isClear", "是")]),
        Step("web_element_click", "点击登录", params=[
            ParamValue("locator", "xpath:://button[@id='login']"),
            ParamValue("isScroll", "是"), ParamValue("scrollMode", "")]),
        Step("web_element_get_element_text", "取欢迎语", params=[
            ParamValue("locator", "css::.welcome"), ParamValue("outVar", "welcomeText")]),
        Step("web_browser_get_url", "取URL", params=[ParamValue("outVar", "curUrl")]),
        Step("web_browser_getBrowserTitle", "取标题", params=[ParamValue("title", "pageTitle")]),
        Step("web_element_get_element_exist", "判存在", params=[
            ParamValue("locator", "id::footer"), ParamValue("outVar", "hasFooter")]),
        Step("web_element_get_element_attribute", "取href", params=[
            ParamValue("locator", "id::link"), ParamValue("name", "href"),
            ParamValue("outVar", "hrefOut")]),   # 参数 id 是 name，验证不再被吞
        Step("web_element_click", "顶部对齐点击", params=[
            ParamValue("locator", "id::top"), ParamValue("isScroll", "是"),
            ParamValue("scrollMode", "顶部")]),   # scrollMode 生效 → scrollIntoView block:'start'
    ]

    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    for r in res.results:
        print(f"  [{r.status:6}] {r.keyword_id:34} {r.comment} {r.message}")

    checks = {
        "url 规范化补 http": fake.current_url == "http://www.example.com",
        "输入文本": fake._elements[("id", "username")].typed == "admin",
        "点击": fake._elements[("xpath", "//button[@id='login']")].clicked,
        "OUT welcomeText": ctx.get_var("welcomeText") == "text@.welcome",
        "OUT curUrl": ctx.get_var("curUrl") == "http://www.example.com",
        "OUT pageTitle": ctx.get_var("pageTitle") == "Fake Title",
        "OUT hasFooter": ctx.get_var("hasFooter") is True,
        "OUT hrefOut(name参数生效)": ctx.get_var("hrefOut") == "/home",
        "scrollMode顶部→start": any("block:'start'" in s for s in getattr(fake, "scripts", [])),
        "无 FAIL": res.counts().get("FAIL", 0) == 0,
    }
    print("  变量池:", {k: ctx.get_var(k) for k in ("welcomeText", "curUrl", "pageTitle", "hasFooter")})
    allok = all(checks.values())
    for k, v in checks.items():
        if not v:
            print("   ❌", k)
    print("Web 流程(FakeDriver):", "✅" if allok else "❌")
    return allok


def test_check_pic_existed() -> bool:
    """图片加载校验：JS 返回失败图 src → 拼进 errorURL(去重保序)；全成功 → 空串。"""
    import types
    from autopilot.keywords.registry import REGISTRY
    from autopilot.keywords.context import ExecutionContext

    class _Drv:
        def __init__(self, broken):
            self._broken = broken
        def execute_script(self, _script="", *_a, **_k):
            return list(self._broken)

    def _run(broken):
        ctx = ExecutionContext()
        # 挂一个最小 web 管理器（.driver() 返回桩 driver）
        ctx.web = types.SimpleNamespace(driver=lambda alias=None: _Drv(broken))  # type: ignore[attr-defined]
        return REGISTRY["ommon_pic_checkPicIsExisted"].func(ctx)

    r1 = _run(["http://x/a.png", "http://x/a.png", "http://x/b.png"])
    r2 = _run([])
    ok = (r1 == {"errorURL": "http://x/a.png;http://x/b.png"}
          and r2 == {"errorURL": ""})
    print("check_pic_existed(失败图去重/全成功空串):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_locator_mapping(), test_web_flow(), test_check_pic_existed()])
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
