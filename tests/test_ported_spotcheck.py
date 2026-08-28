"""关键字实现抽样执行校验：确认关键字真能跑（非空壳/不崩），覆盖各类代表。

纯逻辑（JSON/XML/Verify字符串）直接真实执行；Web/Mobile 用 FakeDriver。
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
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy
from autopilot.keywords.web.driver import get_manager as web_mgr
from autopilot.keywords.mobile.driver import get_manager as mob_mgr


def step(k, c="", **p):
    return Step(k, c, params=[ParamValue(i, v) for i, v in p.items()])


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class FakeEl:
    def __init__(self, text="hi", attrs=None, disp=True, en=True, sel=False):
        self.text, self._a, self._d, self._e, self._s = text, attrs or {}, disp, en, sel
        self.rect = {"x": 0, "y": 0, "width": 100, "height": 100}
    def is_displayed(self): return self._d
    def is_enabled(self): return self._e
    def is_selected(self): return self._s
    def get_attribute(self, n): return self._a.get(n, "")
    def click(self): pass
    def clear(self): pass
    def send_keys(self, _t): pass


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class FakeDrv:
    def __init__(self): self.current_url = "http://x"; self.title = "T"
    def get(self, url): self.current_url = url
    def find_element(self, _by, _v): return FakeEl(text="hello", attrs={"href": "/h"})
    def find_elements(self, _by, _v): return [FakeEl()]
    def execute_script(self, *_a, **_k): return None
    def back(self): pass
    def forward(self): pass


def run(name, ctx, steps):
    tc = TestCase(name=name)
    tc.case.steps = steps
    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    fails = [r for r in res.results if r.status == "FAIL"]
    for r in fails:
        print(f"   ❌ {r.keyword_id}: {r.message}")
    return res, not fails


def main() -> int:
    results = {}

    # --- JSON 关键字抽样（纯逻辑）---
    ctx = ExecutionContext()
    ctx.set_var("js", '{"a":{"b":1},"list":[10,20,30]}')
    _res, ok = run("json", ctx, [
        step("json_get_json_values_num_byjsonpath", "数组个数", json="${js}",
          jsonpath="$.list[*]", num="num"),
    ])
    results["JSON抽样"] = ok and str(ctx.get_var("num")) in ("3", "3.0")
    print(f"JSON抽样: {'✅' if results['JSON抽样'] else '❌'} 数组个数={ctx.get_var('num')}")

    # --- XML 关键字抽样（纯逻辑）---
    ctx = ExecutionContext()
    ctx.set_var("xm", "<r><u id='7'><n>kit</n></u></r>")
    _res, ok = run("xml", ctx, [
        step("xml_get_xml_nodeNum", "节点数", xml="${xm}", xpath="//u", num="cnt"),
    ])
    results["XML抽样"] = ok and str(ctx.get_var("cnt")) == "1"
    print(f"XML抽样: {'✅' if results['XML抽样'] else '❌'} 节点数={ctx.get_var('cnt')}")

    # --- Web verify_ext 抽样（FakeDriver）---
    ctx = ExecutionContext()
    web_mgr(ctx).driver_factory = lambda *_a, **_k: FakeDrv()
    _res, ok = run("web", ctx, [
        step("web_browser_open", "开", url="x", type="Headless"),
        step("web_element_get_element_visible", "可见", locator="id::a", outVar="vis"),
        step("web_element_get_element_attribute", "属性", locator="id::a",
          attribute="href", outVar="hv"),
    ])
    results["Web抽样"] = ok
    print(f"Web抽样: {'✅' if ok else '❌'} 可见={ctx.get_var('vis')} 属性={ctx.get_var('hv')}")

    # --- Mobile element_ext 抽样（FakeDriver）---
    ctx = ExecutionContext()
    mob_mgr(ctx).driver_factory = lambda *_a, **_k: FakeDrv()
    _res, ok = run("mobile", ctx, [
        step("mobile_app_start", "启动", type="Android", packageName="p", activityName="a"),
        step("mobile_element_get_element_visible", "可见", locator="id::x", outVar="mvis"),
    ])
    results["Mobile抽样"] = ok
    print(f"Mobile抽样: {'✅' if ok else '❌'} 可见={ctx.get_var('mvis')}")

    allok = all(results.values())
    print("\n总结:", "✅ 抽样全部可执行" if allok else "❌ 存在不可执行")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
