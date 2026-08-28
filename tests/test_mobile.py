"""阶段6 Mobile 关键字测试（FakeMobileDriver，无需真机/Appium）。

验证：会话创建、点击、输入、清除、取文本/存在、滑动、locator→By、OUT 回写、picture:: 降级。
真机运行作为环境就绪后的额外验证。
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
from autopilot.keywords.mobile.driver import get_manager
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class FakeMobileElement:
    def __init__(self, text="移动文本"):
        self.text = text
        self.clicked = False
        self.cleared = False
        self.typed = ""
        self.rect = {"x": 100, "y": 200, "width": 300, "height": 400}

    def click(self): self.clicked = True
    def clear(self): self.cleared = True
    def send_keys(self, t): self.typed += str(t)


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class FakeMobileDriver:
    def __init__(self):
        self._els = {}
        self.swiped = None
        self.quit_called = False

    def find_element(self, by, value):
        return self._els.setdefault((by, value), FakeMobileElement(text=f"txt@{value}"))

    def swipe(self, sx, sy, ex, ey, dur):
        self.swiped = (sx, sy, ex, ey, dur)

    def quit(self): self.quit_called = True


def main() -> int:
    ctx = ExecutionContext()
    fake = FakeMobileDriver()
    get_manager(ctx).driver_factory = lambda *_a, **_k: fake

    tc = TestCase(name="mobile_demo")
    tc.case.steps = [
        Step("appium_start", "起服务"),
        Step("mobile_app_start", "启动App", params=[
            ParamValue("type", "Android"),
            ParamValue("packageName", "com.example.app"),
            ParamValue("activityName", ".MainActivity")]),
        Step("mobile_element_text_input", "输入", params=[
            ParamValue("locator", "id::search"), ParamValue("text", "手机")]),
        Step("mobile_element_click", "点击", params=[
            ParamValue("locator", "xpath:://*[@text='搜索']"), ParamValue("timeout", "30")]),
        Step("mobile_element_get_element_text", "取文本", params=[
            ParamValue("locator", "id::title"), ParamValue("outVar", "title")]),
        Step("mobile_element_get_element_exist", "判存在", params=[
            ParamValue("locator", "id::cart"), ParamValue("outVar", "hasCart")]),
        Step("mobile_element_swipe", "上滑", params=[
            ParamValue("locator", "id::list"), ParamValue("direction", "上")]),
        Step("mobile_element_text_clear", "清空", params=[
            ParamValue("locator", "id::search")]),
        Step("mobile_app_close", "关闭App"),
    ]

    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    for r in res.results:
        print(f"  [{r.status:6}] {r.keyword_id:34} {r.comment} {r.message}")

    # noinspection PyProtectedMember
    checks = {
        "输入": fake._els[("id", "search")].typed == "手机",
        "点击": fake._els[("xpath", "//*[@text='搜索']")].clicked,
        "OUT title": ctx.get_var("title") == "txt@title",
        "OUT hasCart": ctx.get_var("hasCart") is True,
        "滑动已触发": fake.swiped is not None,
        "清空": fake._els[("id", "search")].cleared,
        "关闭App": fake.quit_called,
        "无FAIL": res.counts().get("FAIL", 0) == 0,
    }
    ok = all(checks.values())
    for k, v in checks.items():
        if not v:
            print("   ❌", k)
    print("\n移动端流程(FakeDriver):", "✅ 通过" if ok else "❌ 失败")

    # picture:: 现已用 opencv 实现：截屏匹配模板图 → tap 命中坐标
    # noinspection PyPackageRequirements
    import tempfile
    import numpy as np
    import cv2
    tmp = tempfile.mkdtemp()
    # 造一张场景图，在 (120,260) 放带纹理目标块，并保存模板
    scene = np.zeros((600, 300, 3), np.uint8)
    for y in range(600):
        scene[y, :] = (y % 80 + 30, (y * 2) % 180 + 20, 100)
    blk = np.zeros((40, 50, 3), np.uint8)
    cv2.rectangle(blk, (0, 0), (49, 39), (0, 0, 255), -1)
    cv2.line(blk, (0, 0), (49, 39), (0, 255, 0), 3)
    scene[240:280, 95:145] = blk
    scene_png = cv2.imencode(".png", scene)[1].tobytes()
    tmpl_path = os.path.join(tmp, "btn.png")
    cv2.imwrite(tmpl_path, blk)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class PicDrv(FakeMobileDriver):
        def get_screenshot_as_png(self): return scene_png
        def get_window_size(self): return {"width": 300, "height": 600}
        def __init__(self): super().__init__(); self.tapped = None
        def tap(self, points, _dur=None): self.tapped = points[0]

    picdrv = PicDrv()
    ctx2 = ExecutionContext()
    get_manager(ctx2).driver_factory = lambda *_a, **_k: picdrv
    tc2 = TestCase(name="pic")
    tc2.case.steps = [
        Step("mobile_app_start", "启动", params=[ParamValue("type", "Android")]),
        Step("mobile_element_click", "图像点击",
             params=[ParamValue("locator", f"picture::{tmpl_path}")]),
    ]
    res2 = Executor(ctx2).run_testcase(tc2)
    # 目标中心约 (120,260)；窗口=截图尺寸故无缩放
    tapped = picdrv.tapped
    pic_ok = (res2.results[-1].status == "PASS" and tapped is not None
              and abs(tapped[0] - 120) <= 4 and abs(tapped[1] - 260) <= 4)
    print("picture:: 图像点击(opencv+tap):", "✅" if pic_ok else "❌", "tap=", tapped)

    allok = ok and pic_ok
    print("\n总结:", "✅ 全部通过" if allok else "❌ 存在失败")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
