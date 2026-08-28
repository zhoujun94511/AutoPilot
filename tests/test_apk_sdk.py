"""APK 解析(pyaxmlparser) + SDK 控件遍历 测试。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.mobile.driver import get_manager
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy

# 复用本地真实 apk 验证解析
APK = r"D:/projectx/WebAppFlaskscrcpy/.venv/Lib/site-packages/uiautomator2/assets/app-uiautomator.apk"
IPA = r"D:/plantscope/AIID/ipa/aitou.ipa"
IPA_BUNDLE = "imobile.broadcast.app"


def test_ipa_parse() -> bool:
    if not os.path.exists(IPA):
        print("IPA 解析: ⏭ 跳过(无样例 ipa)")
        return True
    ctx = ExecutionContext()
    tc = TestCase(name="ipa")
    tc.case.steps = [
        Step("mobile_app_get_package_and_activity", "解析ipa", params=[
            ParamValue("appFile", IPA),
        ]),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.STOP).run_testcase(tc)
    ok = (res.counts().get("FAIL", 0) == 0
          and ctx.get_var("app_package") == IPA_BUNDLE)
    print("IPA 解析:", "✅" if ok else "❌",
          "app_package=", ctx.get_var("app_package"))
    return ok


def test_apk_parse() -> bool:
    if not os.path.exists(APK):
        print("APK 解析: ⏭ 跳过(无样例 apk)")
        return True
    ctx = ExecutionContext()
    tc = TestCase(name="apk")
    tc.case.steps = [
        Step("mobile_app_get_package_and_activity", "解析apk", params=[
            ParamValue("appFile", APK),
        ]),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.STOP).run_testcase(tc)
    ok = (res.counts().get("FAIL", 0) == 0
          and ctx.get_var("app_package") == "com.github.uiautomator"
          and "MainActivity" in (ctx.get_var("app_activity") or ""))
    print("APK 解析(pyaxmlparser):", "✅" if ok else "❌",
          "app_package=", ctx.get_var("app_package"),
          "app_activity=", ctx.get_var("app_activity"))
    return ok


PAGE_SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node clickable="false" bounds="[0,0][1080,200]">
    <node resource-id="a" text="按钮1" clickable="true" bounds="[10,210][200,300]"/>
    <node resource-id="b" text="按钮2" clickable="true" bounds="[10,310][200,400]"/>
    <node resource-id="c" text="文本" clickable="false" bounds="[10,410][200,500]"/>
  </node>
</hierarchy>"""


class FakeSDKDriver:
    def __init__(self): self.taps = []
    @property
    def page_source(self): return PAGE_SOURCE
    def tap(self, points, _dur=None): self.taps.append(points[0])
    def back(self): pass


def test_sdk_ergodic() -> bool:
    ctx = ExecutionContext()
    fake = FakeSDKDriver()
    get_manager(ctx).driver_factory = lambda *_a, **_k: fake
    tc = TestCase(name="sdk")
    tc.case.steps = [
        Step("mobile_app_start", "启动", params=[ParamValue("type", "Android")]),
        Step("mobile_SDK_ergodic", "遍历", params=[
            ParamValue("type", "android"), ParamValue("depth", "1")]),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    # 2 个 clickable=true 节点应被点击（中心点）
    ok = (res.counts().get("FAIL", 0) == 0 and len(fake.taps) == 2
          and fake.taps[0] == (105, 255) and fake.taps[1] == (105, 355))
    print("SDK 控件遍历:", "✅" if ok else "❌", "taps=", fake.taps)
    return ok


def main() -> int:
    ok = all([test_apk_parse(), test_ipa_parse(), test_sdk_ergodic()])
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
