"""图像识别测试：opencv 匹配核心 + WebUI img_* + Mobile picture:: 。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
# noinspection PyPackageRequirements
import cv2

from autopilot.keywords.image_match import find_template
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.web.driver import get_manager as web_mgr
from autopilot.keywords.mobile.driver import get_manager as mob_mgr
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy


def _textured_block(w=48, h=36):
    blk = np.zeros((h, w, 3), np.uint8)
    cv2.rectangle(blk, (0, 0), (w - 1, h - 1), (255, 0, 0), -1)
    cv2.line(blk, (0, 0), (w - 1, h - 1), (0, 255, 255), 3)
    cv2.circle(blk, (w // 2, h // 2), 6, (0, 255, 0), -1)
    return blk


def _scene(h, w, block, by, bx):
    s = np.zeros((h, w, 3), np.uint8)
    for y in range(h):
        s[y, :] = (y % 70 + 30, (y * 3) % 170 + 20, 90)
    bh, bw = block.shape[:2]
    s[by:by + bh, bx:bx + bw] = block
    return s


def test_core():
    blk = _textured_block()
    scene = _scene(400, 600, blk, 150, 300)
    png = cv2.imencode(".png", scene)[1].tobytes()
    tmp = tempfile.mkdtemp()
    tp = os.path.join(tmp, "b.png")
    cv2.imwrite(tp, blk)
    m = find_template(png, tp, threshold=0.8)
    ok = m and abs(m.cx - 324) <= 3 and abs(m.cy - 168) <= 3 and m.score > 0.99
    print("匹配核心:", "✅" if ok else "❌", m)
    return ok, tp, png


def _check_web_img(tp, scene_png):  # 辅助函数（依赖 test_core 产物），非独立用例，勿加 test_ 前缀
    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class WD:
        current_url = "http://x"
        def get(self, _u): pass
        def get_screenshot_as_png(self): return scene_png
        def execute_script(self, *a, **_k):
            return 1 if (a and "devicePixelRatio" in str(a[0])) else True
    ctx = ExecutionContext()
    web_mgr(ctx).driver_factory = lambda *_a, **_k: WD()
    tc = TestCase(name="webimg")
    tc.case.steps = [
        Step("web_browser_open", "", params=[ParamValue("url", "x"), ParamValue("type", "Headless")]),
        Step("img_element_exists", "", params=[ParamValue("imagePath", tp),
             ParamValue("expectExist", "true"), ParamValue("outVar", "found")]),
        Step("img_element_click", "", params=[ParamValue("imagePath", tp)]),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    ok = ctx.get_var("found") is True and res.counts().get("FAIL", 0) == 0
    print("WebUI 图像关键字:", "✅" if ok else "❌", "found=", ctx.get_var("found"))
    return ok


def test_mobile_picture():
    blk = _textured_block(50, 40)
    scene = _scene(600, 300, blk, 240, 95)
    png = cv2.imencode(".png", scene)[1].tobytes()
    tmp = tempfile.mkdtemp()
    tp = os.path.join(tmp, "btn.png")
    cv2.imwrite(tp, blk)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class MD:
        tapped: tuple[float, float] | None

        def __init__(self): self.tapped = None
        def get_screenshot_as_png(self): return png
        def get_window_size(self): return {"width": 300, "height": 600}
        def tap(self, points, _dur=None): self.tapped = points[0]
    md = MD()
    ctx = ExecutionContext()
    mob_mgr(ctx).driver_factory = lambda *_a, **_k: md
    tc = TestCase(name="mobimg")
    tc.case.steps = [
        Step("mobile_app_start", "", params=[ParamValue("type", "Android")]),
        Step("mobile_element_click", "", params=[ParamValue("locator", f"picture::{tp}")]),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    # 目标中心约 (120,260)
    tap_abs = md.tapped
    ok_abs = (res.counts().get("FAIL", 0) == 0 and tap_abs is not None
              and abs(tap_abs[0] - 120) <= 4 and abs(tap_abs[1] - 260) <= 4)

    # 相对路径：依赖 __project_path__（与框选写入 picture::images/... 对齐）
    md.tapped = None
    ctx2 = ExecutionContext()
    ctx2.set_var("__project_path__", tmp)
    mob_mgr(ctx2).driver_factory = lambda *_a, **_k: md
    tc2 = TestCase(name="mobimg_rel")
    tc2.case.steps = [
        Step("mobile_app_start", "", params=[ParamValue("type", "Android")]),
        Step("mobile_element_click", "", params=[
            ParamValue("locator", "picture::btn.png"),
            ParamValue("accuracy", "精确匹配"),
        ]),
    ]
    res2 = Executor(ctx2, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc2)
    tap_rel = md.tapped
    ok_rel = (res2.counts().get("FAIL", 0) == 0 and tap_rel is not None
              and abs(tap_rel[0] - 120) <= 4 and abs(tap_rel[1] - 260) <= 4)
    ok = ok_abs and ok_rel
    print("Mobile picture:: 点击:", "✅" if ok else "❌",
          "abs=", ok_abs, "rel=", ok_rel, "tap=", md.tapped)
    return ok


def main() -> int:
    core_ok, tp, scene_png = test_core()
    ok = all([core_ok, _check_web_img(tp, scene_png), test_mobile_picture()])
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
