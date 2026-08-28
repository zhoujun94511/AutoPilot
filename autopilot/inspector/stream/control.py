"""控制汇（ControlSink）：把「在镜像上的操作」转成对真机的控制动作。

与帧源(ScreenSource)对称、互相解耦：帧源把设备画面送上来，控制汇把用户在画面上的
点/拖/输入/系统键送下去。统一以**设备坐标**收参（像素/点，见各实现）。

能力模型：`capabilities()` 返回该平台支持的「按钮/动作」集合，镜像面板据此**数据驱动**
显隐按钮（不同平台能做的不一样，按钮就只显示能做的）。

动作面（按测试 IDE 实际需要裁剪，不做多点触控/UHID/无障碍等边缘项）：
  手势：tap / swipe / scroll / long_press / double_tap
  系统键：key(name) —— back/home/recents/volume_up/volume_down/power/menu/notifications/settings/collapse/rotate/lock/screenshot
  文本：text(s)
  剪贴板：get_clipboard() / set_clipboard(text)
"""

from __future__ import annotations

from typing import Optional

# 能力键常量（面板与实现共用，避免拼写漂移）
CAP_LONG_PRESS = "long_press"
CAP_DOUBLE_TAP = "double_tap"
CAP_CLIPBOARD_GET = "clipboard_get"
CAP_CLIPBOARD_SET = "clipboard_set"
# 系统键能力即键名本身（back/home/recents/...）


class ControlSink:
    """设备控制动作接口（坐标为设备坐标）。子类按平台实现并声明 capabilities()。"""

    def capabilities(self) -> set:
        """该平台支持的动作/按钮键集合（面板据此显隐按钮）。"""
        return set()

    def resolution(self) -> Optional[tuple]:
        return None

    # ---- 手势 ----
    def tap(self, x: float, y: float) -> None:
        raise NotImplementedError

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 200) -> None:
        raise NotImplementedError

    def long_press(self, x: float, y: float, duration_ms: int = 600) -> None:
        # 默认用一次原地慢 swipe 近似
        self.swipe(x, y, x, y, duration_ms)

    def double_tap(self, x: float, y: float) -> None:
        self.tap(x, y)
        self.tap(x, y)

    def scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        self.swipe(x, y, x - dx, y - dy, duration_ms=120)

    # ---- 文本 / 系统键 ----
    def text(self, s: str) -> None:
        raise NotImplementedError

    def key(self, name: str) -> None:
        """系统按键/面板动作（平台不支持的忽略）。"""

    # ---- 剪贴板 ----
    def get_clipboard(self) -> str:
        return ""

    def set_clipboard(self, text: str) -> None:
        pass


class ScrcpyControlSink(ControlSink):
    """Android：投递到 scrcpy 控制通道（坐标=视频帧像素=控制坐标空间）。"""

    _KEYCODE_KEYS = {"home", "recents", "volume_up", "volume_down", "power", "menu",
                     "enter", "delete"}

    def __init__(self, core) -> None:
        self._core = core
        from . import _scrcpy_core as c
        self._kc = c.KEYCODE

    def capabilities(self) -> set:
        return {CAP_LONG_PRESS, CAP_DOUBLE_TAP, CAP_CLIPBOARD_SET, CAP_CLIPBOARD_GET,
                "back", "home", "recents", "volume_up", "volume_down",
                "power", "notifications", "settings", "collapse", "rotate", "screenshot"}

    def resolution(self) -> Optional[tuple]:
        return getattr(self._core, "resolution", None)

    def tap(self, x, y) -> None:
        self._core.tap(x, y)

    def swipe(self, x1, y1, x2, y2, duration_ms: int = 200) -> None:
        self._core.swipe(x1, y1, x2, y2, duration_ms)

    def long_press(self, x, y, duration_ms: int = 600) -> None:
        self._core.long_press(x, y, duration_ms)

    def double_tap(self, x, y) -> None:
        self._core.double_tap(x, y)

    def scroll(self, x, y, dx, dy) -> None:
        self._core.scroll(x, y, dx, dy)

    def text(self, s: str) -> None:
        self._core.text(s)

    def key(self, name: str) -> None:
        if name == "back":
            self._core.back()
        elif name == "recents":
            self._core.keycode(self._kc["app_switch"])
        elif name == "notifications":
            self._core.expand_notifications()
        elif name == "settings":
            self._core.expand_settings()
        elif name == "collapse":
            self._core.collapse_panels()
        elif name == "rotate":
            self._core.rotate()
        elif name == "power":
            self._core.keycode(self._kc["power"])   # 注入电源键(锁屏/唤醒)
        elif name in self._kc:
            self._core.keycode(self._kc[name])

    def set_clipboard(self, text: str) -> None:
        self._core.set_clipboard(text, paste=True)

    def get_clipboard(self) -> str:
        return self._core.get_clipboard()


class WdaControlSink(ControlSink):
    """iOS：投递到 WDA HTTP。传入的 (x,y) 是设备点坐标（上层已按比例换算）。"""

    def __init__(self, client) -> None:
        self._c = client
        self._win = None

    def capabilities(self) -> set:
        return {CAP_LONG_PRESS, CAP_DOUBLE_TAP, CAP_CLIPBOARD_GET, CAP_CLIPBOARD_SET,
                "home", "volume_up", "volume_down", "lock", "screenshot"}

    def resolution(self) -> Optional[tuple]:
        if self._win is None:
            # noinspection PyBroadException
            try:
                w = self._c.window_size() or {}
                self._win = (int(w.get("width", 0)), int(w.get("height", 0)))
            except Exception:
                self._win = (0, 0)
        return self._win if self._win and self._win[0] else None

    def tap(self, x, y) -> None:
        self._c.tap(int(x), int(y))

    def swipe(self, x1, y1, x2, y2, duration_ms: int = 200) -> None:
        # 横向优先 XCTest drag（分页 carousel 不回弹）；失败回退 W3C actions
        # noinspection PyBroadException
        try:
            if abs(x2 - x1) >= abs(y2 - y1):
                self._c.drag_from_to_for_duration(int(x1), int(y1), int(x2), int(y2))
                return
        except Exception:
            pass
        self._c.actions(self._pointer([
            {"type": "pointerMove", "duration": 0, "x": int(x1), "y": int(y1)},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": int(duration_ms), "x": int(x2), "y": int(y2)},
            {"type": "pointerUp", "button": 0},
        ]))

    def long_press(self, x, y, duration_ms: int = 600) -> None:
        self._c.actions(self._pointer([
            {"type": "pointerMove", "duration": 0, "x": int(x), "y": int(y)},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": int(duration_ms)},
            {"type": "pointerUp", "button": 0},
        ]))

    def double_tap(self, x, y) -> None:
        self._c.double_tap(int(x), int(y))

    @staticmethod
    def _pointer(actions: list) -> list:
        return [{"type": "pointer", "id": "finger1",
                 "parameters": {"pointerType": "touch"}, "actions": actions}]

    def text(self, s: str) -> None:
        self._c.send_keys(s)

    def key(self, name: str) -> None:
        if name == "home":
            self._c.home()
        elif name == "volume_up":
            self._c.press_button("volumeUp")
        elif name == "volume_down":
            self._c.press_button("volumeDown")
        elif name == "screenshot":
            self._c.press_button("snapshot")
        elif name == "lock":
            # 切换：已锁→解锁(唤醒)，未锁→锁屏。否则只能锁、无法唤醒。
            # noinspection PyBroadException
            try:
                self._c.unlock() if self._c.locked() else self._c.lock()
            except Exception:
                self._c.lock()
        elif name == "enter":
            self._c.send_keys("\n")
        elif name == "delete":
            self._c.send_keys("\b")

    def get_clipboard(self) -> str:
        return self._c.get_pasteboard()

    def set_clipboard(self, text: str) -> None:
        self._c.set_pasteboard(text)


def _appium_touch_actions(drv, fn) -> bool:
    """W3C touch ActionChains；成功返回 True。"""
    # noinspection PyBroadException
    try:
        from selenium.webdriver.common.actions import interaction
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
        actions = ActionBuilder(drv, mouse=pointer)
        fn(actions.pointer_action)
        actions.perform()
        return True
    except Exception:
        return False


class AppiumControlSink(ControlSink):
    """iOS Appium：经 Appium driver 下发手势/按键（勿直连 8100，session_id 与 WDA 不一致）。"""

    _BTN = {"home": "home", "volume_up": "volumeUp", "volume_down": "volumeDown",
            "screenshot": "snapshot"}

    def __init__(self, driver_provider) -> None:
        self._driver_provider = driver_provider

    def _drv(self):
        return self._driver_provider()

    def capabilities(self) -> set:
        return {CAP_LONG_PRESS, CAP_DOUBLE_TAP, CAP_CLIPBOARD_GET, CAP_CLIPBOARD_SET,
                "home", "volume_up", "volume_down", "lock", "screenshot"}

    def resolution(self) -> Optional[tuple]:
        # noinspection PyBroadException
        try:
            w = self._drv().get_window_size() or {}
            ww, hh = int(w.get("width", 0)), int(w.get("height", 0))
            return (ww, hh) if ww and hh else None
        except Exception:
            return None

    def tap(self, x, y) -> None:
        drv = self._drv()
        ix, iy = int(x), int(y)
        if _appium_touch_actions(drv, lambda a: (
            a.move_to_location(ix, iy), a.pointer_down(), a.pause(0.1), a.pointer_up()
        )):
            return
        # noinspection PyBroadException
        try:
            drv.tap([(ix, iy)])
            return
        except Exception:
            pass
        drv.execute_script("mobile: clickGesture", {"x": ix, "y": iy})

    def swipe(self, x1, y1, x2, y2, duration_ms: int = 200) -> None:
        drv = self._drv()
        ix1, iy1, ix2, iy2 = int(x1), int(y1), int(x2), int(y2)
        dur = max(50, int(duration_ms))
        if _appium_touch_actions(drv, lambda a: (
            a.move_to_location(ix1, iy1), a.pointer_down(),
            a.pause(dur / 1000.0), a.move_to_location(ix2, iy2), a.pointer_up()
        )):
            return
        # noinspection PyBroadException
        try:
            drv.swipe(ix1, iy1, ix2, iy2, dur)
            return
        except Exception:
            pass
        drv.execute_script("mobile: dragFromToForDuration", {
            "fromX": ix1, "fromY": iy1, "toX": ix2, "toY": iy2,
            "duration": dur / 1000.0,
        })

    def long_press(self, x, y, duration_ms: int = 600) -> None:
        drv = self._drv()
        ix, iy = int(x), int(y)
        dur = max(100, int(duration_ms))
        if _appium_touch_actions(drv, lambda a: (
            a.move_to_location(ix, iy), a.pointer_down(),
            a.pause(dur / 1000.0), a.pointer_up()
        )):
            return
        # noinspection PyBroadException
        try:
            drv.long_press(ix, iy, dur)
            return
        except Exception:
            pass
        drv.execute_script("mobile: longClickGesture",
                                 {"x": ix, "y": iy, "duration": dur})

    def double_tap(self, x, y) -> None:
        drv = self._drv()
        ix, iy = int(x), int(y)
        # noinspection PyBroadException
        try:
            drv.execute_script("mobile: doubleTap", {"x": ix, "y": iy})
            return
        except Exception:
            pass
        self.tap(ix, iy)
        self.tap(ix, iy)

    def scroll(self, x, y, dx, dy) -> None:
        self.swipe(x, y, x - dx, y - dy, duration_ms=120)

    def text(self, s: str) -> None:
        drv = self._drv()
        # noinspection PyBroadException
        try:
            drv.execute_script("mobile: type", {"text": str(s)})
            return
        except Exception:
            pass
        # noinspection PyBroadException
        try:
            drv.execute_script("mobile: keys", {"keys": list(str(s))})
        except Exception:
            drv.set_value(str(s))

    def key(self, name: str) -> None:
        drv = self._drv()
        if name == "lock":
            # noinspection PyBroadException
            try:
                locked = bool(drv.execute_script("mobile: isLocked"))
                script = "mobile: unlock" if locked else "mobile: lock"
                drv.execute_script(script)
                return
            except Exception:
                pass
        btn = self._BTN.get(name)
        if btn:
            drv.execute_script("mobile: pressButton", {"name": btn})
        elif name == "enter":
            self.text("\n")
        elif name == "delete":
            self.text("\b")

    def get_clipboard(self) -> str:
        drv = self._drv()
        # noinspection PyBroadException
        try:
            return str(drv.get_clipboard_text() or "")
        except Exception:
            pass
        # noinspection PyBroadException
        try:
            return str(drv.execute_script("mobile: getPasteboard", {}) or "")
        except Exception:
            return ""

    def set_clipboard(self, text: str) -> None:
        drv = self._drv()
        # noinspection PyBroadException
        try:
            drv.set_clipboard_text(str(text))
            return
        except Exception:
            pass
        drv.execute_script("mobile: setPasteboard", {"content": str(text)})
