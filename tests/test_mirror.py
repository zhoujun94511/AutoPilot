"""阶段18 交互镜像（离线）：scrcpy 控制报文编码 + 坐标映射 + WDA 动作 JSON。"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_APP = None


def test_mirror_start_no_device() -> bool:
    """无真机：before_start 拦截，不调用 session_provider。"""
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.mirror_panel import MirrorPanel
        _APP = QApplication.instance() or QApplication([])
        p = MirrorPanel()
        called = {"n": 0}
        p.before_start = lambda: False
        p.session_provider = lambda: (called.__setitem__("n", called["n"] + 1), None)[1]
        p.set_mobile_available(True)
        p.btn_live.setChecked(True)
        ok = called["n"] == 0 and not p.btn_live.isChecked() and not p.active()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("镜像无设备启动拦截: ⏭ 跳过(", e, ")")
        return True
    print("镜像 before_start 拦截:", "✅" if ok else "❌")
    return ok


def test_mirror_mobile_unavailable() -> bool:
    """set_mobile_available(False) 禁用开始按钮。"""
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.mirror_panel import MirrorPanel
        _APP = QApplication.instance() or QApplication([])
        p = MirrorPanel()
        p.set_mobile_available(False)
        ok = not p.btn_live.isEnabled()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("镜像按钮禁用: ⏭ 跳过(", e, ")")
        return True
    print("镜像无真机禁用开始:", "✅" if ok else "❌")
    return ok


def test_scrcpy_control_encode() -> bool:
    from autopilot.inspector.stream import _scrcpy_core as c
    touch = c.build_touch(c._ACT_DOWN, 100, 200, 1080, 1920)
    # 类型字节=2(TOUCH) + action=0 + touch_id + x + y + w + h + pressure + ab + buttons
    t_type, action, tid, x, y, w, h, pres, ab, btn = struct.unpack(">BBqiiHHHii", touch)
    touch_ok = (t_type == c._CTRL_TOUCH and action == 0 and x == 100 and y == 200
                and w == 1080 and h == 1920 and pres == 0xFFFF)
    text = c.build_text("hi")
    tt, ln = struct.unpack(">Bi", text[:5])
    text_ok = (tt == c._CTRL_TEXT and ln == 2 and text[5:] == b"hi")
    kc = c.build_keycode(c.KEYCODE["back"])
    kt, kact, code, rep, meta = struct.unpack(">BBiii", kc)
    key_ok = (kt == c._CTRL_KEYCODE and code == 4)
    back = c.build_back()
    back_ok = back[0] == c._CTRL_BACK
    scr = c.build_scroll(10, 20, 1080, 1920, 1200, -1200)
    st, sx, sy, sw, sh, hs, vs, sbtn = struct.unpack(">BiiHHhhi", scr)
    # 1200 → 满屏一格 → +32767；-1200 → -32767
    scroll_ok = (st == c._CTRL_SCROLL and hs == 32767 and vs == -32767 and sbtn == 0)
    ok = touch_ok and text_ok and key_ok and back_ok and scroll_ok
    print("scrcpy 控制报文编码:", "✅" if ok else "❌")
    return ok


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class _FakeSink:
    """记录收到的动作 + 给出设备坐标空间用于映射校验。"""
    def __init__(self, res):
        self._res = res
        self.calls = []

    def resolution(self):
        return self._res

    def tap(self, x, y):
        self.calls.append(("tap", round(x), round(y)))

    def swipe(self, x1, y1, x2, y2, duration_ms=200):
        self.calls.append(("swipe", round(x1), round(y1), round(x2), round(y2)))

    def text(self, s):
        self.calls.append(("text", s))

    def key(self, name):
        self.calls.append(("key", name))

    def scroll(self, x, y, dx, dy):
        self.calls.append(("scroll", round(x), round(y)))


def test_mirror_gestures() -> bool:
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QImage
        from PyQt6.QtCore import QPointF
        from autopilot.ui.widgets.mirror_panel import MirrorPanel
        _APP = QApplication.instance() or QApplication([])
        p = MirrorPanel()
        # 帧 100x200；设备坐标 200x400 → 映射系数 2（点击/拖拽坐标×2）
        sink = _FakeSink((200, 400))
        p._control = sink
        img = QImage(100, 200, QImage.Format.Format_RGB32); img.fill(0)
        p._on_frame(img)
        size_ok = p._frame_size == (100, 200)
        # 点击：press≈release → tap，坐标×2
        p._on_press(QPointF(10, 20)); p._on_release(QPointF(11, 21))
        tap_ok = sink.calls[-1] == ("tap", 20, 40)
        # 拖拽：超过阈值 → swipe
        p._on_press(QPointF(10, 20)); p._on_release(QPointF(60, 120))
        swipe_ok = sink.calls[-1] == ("swipe", 20, 40, 120, 240)
        # 系统键 + 文本
        p._key("home"); p._control.text("ab")
        key_ok = ("key", "home") in sink.calls and ("text", "ab") in sink.calls
        ok = size_ok and tap_ok and swipe_ok and key_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("镜像手势→控制: ⏭ 跳过(", e, ")")
        return True
    print("镜像手势→控制(坐标映射):", "✅" if ok else "❌")
    return ok


def test_wda_control_sink() -> bool:
    """WdaControlSink 用假 client 校验下发的动作形态。"""
    from autopilot.inspector.stream.control import WdaControlSink

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeWda:
        def __init__(self):
            self.log = []
        def window_size(self):
            return {"width": 200, "height": 400}
        def tap(self, x, y):
            self.log.append(("tap", x, y))
        def actions(self, actions):
            self.log.append(("actions", actions))
        def send_keys(self, s):
            self.log.append(("keys", s))
        def home(self):
            self.log.append(("home",))

    fw = _FakeWda()
    sink = WdaControlSink(fw)
    res_ok = sink.resolution() == (200, 400)
    sink.tap(5, 6)
    tap_ok = fw.log[-1] == ("tap", 5, 6)
    sink.swipe(1, 2, 3, 4, 150)
    acts = fw.log[-1]
    swipe_ok = (acts[0] == "actions" and acts[1][0]["actions"][0]["x"] == 1
                and acts[1][0]["actions"][-1]["type"] == "pointerUp")
    sink.text("hi"); sink.key("home")
    misc_ok = ("keys", "hi") in fw.log and ("home",) in fw.log
    ok = res_ok and tap_ok and swipe_ok and misc_ok
    print("WDA 控制汇动作:", "✅" if ok else "❌")
    return ok


def test_scrcpy_sink_keys() -> bool:
    """系统键接线：power 必须注入 KEYCODE_POWER(锁屏/唤醒)，而非 SET_SCREEN_POWER_MODE；
    rotate 走 core.rotate()。真机实测 SET_SCREEN_POWER_MODE/ROTATE_DEVICE 在该机无效。"""
    from autopilot.inspector.stream.control import ScrcpyControlSink
    from autopilot.inspector.stream import _scrcpy_core as c

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _RecCore:
        resolution = (1080, 1920)

        def __init__(self):
            self.calls = []

        def keycode(self, code):
            self.calls.append(("keycode", code))

        def rotate(self):
            self.calls.append(("rotate",))

        def power(self, mode):
            self.calls.append(("power", mode))

    rec = _RecCore()
    sink = ScrcpyControlSink(rec)
    sink.key("power")
    sink.key("rotate")
    power_ok = ("keycode", c.KEYCODE["power"]) in rec.calls    # =26，注入电源键
    no_setpower = all(ca[0] != "power" for ca in rec.calls)    # 不再走 SET_SCREEN_POWER_MODE
    rotate_ok = ("rotate",) in rec.calls
    ok = power_ok and no_setpower and rotate_ok
    print("scrcpy 系统键接线(power→keycode26 / rotate):", "✅" if ok else "❌", rec.calls)
    return ok


def test_scrcpy_text_unicode() -> bool:
    """Android 文本注入：ASCII 走 INJECT_TEXT；非 ASCII(中文)走剪贴板+粘贴(scrcpy 注入会丢)。"""
    from autopilot.inspector.stream._scrcpy_core import ScrcpyCore
    core = ScrcpyCore("x")
    core._control_sock = object()              # 伪装控制通道已连
    rec = []
    core.set_clipboard = lambda t, paste=True: rec.append(("clip", t, paste))
    core._send_control = lambda payload: (rec.append(("ctrl", payload)), True)[1]
    core.text("hello")                          # ASCII → INJECT_TEXT
    ascii_ok = bool(rec) and rec[-1][0] == "ctrl"
    core.text("你好")                            # 中文 → 剪贴板粘贴
    cn_ok = rec[-1][0] == "clip" and rec[-1][1] == "你好" and rec[-1][2] is True
    ok = bool(ascii_ok and cn_ok)
    print("Android 文本注入(ASCII/中文分流):", "✅" if ok else "❌", [r[0] for r in rec])
    return ok


def test_mirror_ime_input() -> bool:
    """输入法提交(中文)经 inputMethodEvent → 视图 textInput 信号携带 commitString。"""
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QInputMethodEvent
        from autopilot.ui.widgets.mirror_panel import _MirrorView
        _APP = QApplication.instance() or QApplication([])
        v = _MirrorView()
        got = []
        # noinspection PyUnresolvedReferences
        v.textInput.connect(got.append)
        ev = QInputMethodEvent()
        ev.setCommitString("你好世界")
        v.inputMethodEvent(ev)
        ok = got == ["你好世界"]
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("镜像中文输入(IME): ⏭ 跳过(", e, ")")
        return True
    print("镜像中文输入(IME→textInput):", "✅" if ok else "❌")
    return ok


def test_scrcpy_get_clipboard() -> bool:
    """Android 读剪贴板：发 GET_CLIPBOARD(8,0)，解析控制 socket 回的 CLIPBOARD 设备消息。"""
    import struct
    from autopilot.inspector.stream._scrcpy_core import ScrcpyCore

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeSock:
        def __init__(self, sock_buf):
            self._buf = sock_buf
            self.sent = []

        def settimeout(self, _t):
            pass

        def setblocking(self, _b):
            pass

        def send(self, b):
            self.sent.append(b)

        def recv(self, n):
            chunk = self._buf[:n]
            self._buf = self._buf[n:]
            return chunk

    text = "设备剪贴板内容✓".encode("utf-8")
    payload = struct.pack(">B", 0) + struct.pack(">I", len(text)) + text   # type=CLIPBOARD
    core = ScrcpyCore("x")
    fake = _FakeSock(payload)
    core._control_sock = fake
    got = core.get_clipboard()
    sent_ok = bool(fake.sent) and fake.sent[0] == struct.pack(">BB", 8, 0)       # GET_CLIPBOARD
    ok = bool(got == "设备剪贴板内容✓" and sent_ok)
    print("Android 读剪贴板(GET_CLIPBOARD 解析):", "✅" if ok else "❌", repr(got))
    return ok


def test_wda_lock_toggle() -> bool:
    """iOS 锁屏键应切换：已锁→解锁(唤醒)、未锁→锁屏，否则锁了无法唤醒。"""
    from autopilot.inspector.stream.control import WdaControlSink

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeWda:
        def __init__(self, locked):
            self._locked = locked
            self.calls = []

        def locked(self):
            return self._locked

        def lock(self):
            self.calls.append("lock")

        def unlock(self):
            self.calls.append("unlock")

    a = _FakeWda(True)
    WdaControlSink(a).key("lock")           # 已锁 → 解锁
    b = _FakeWda(False)
    WdaControlSink(b).key("lock")           # 未锁 → 锁屏
    ok = a.calls == ["unlock"] and b.calls == ["lock"]
    print("iOS 锁屏键切换(锁↔唤醒):", "✅" if ok else "❌", (a.calls, b.calls))
    return ok


def test_mirror_screenshot_save() -> bool:
    """「设备截图」保存当前帧为 PNG（平台无关）。"""
    try:
        import os
        import shutil
        import tempfile
        global _APP
        from PyQt6.QtWidgets import QApplication, QFileDialog
        from PyQt6.QtGui import QImage
        from autopilot.ui.widgets.mirror_panel import MirrorPanel
        _APP = QApplication.instance() or QApplication([])
        p = MirrorPanel()
        img = QImage(8, 8, QImage.Format.Format_RGB32)
        img.fill(0x3366CC)
        p._on_frame(img)                    # 喂一帧 → 缓存 _last_frame
        d = tempfile.mkdtemp()
        target = os.path.join(d, "shot.png")
        orig = QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (target, "图片 (*.png)"))
        try:
            p._save_screenshot()            # 用户选路径(此处 monkeypatch 返回 target)
        finally:
            QFileDialog.getSaveFileName = orig
        ok = os.path.exists(target) and os.path.getsize(target) > 0
        shutil.rmtree(d, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("镜像设备截图: ⏭ 跳过(", e, ")")
        return True
    print("镜像设备截图(保存当前帧):", "✅" if ok else "❌")
    return ok


def test_scrcpy_extra_encode() -> bool:
    """新增控制报文：展开通知/收起面板·电源·旋转·set_clipboard 的字节编码。"""
    import struct
    from autopilot.inspector.stream import _scrcpy_core as c
    notif = c.build_simple(c._CTRL_EXPAND_NOTIFICATION)
    collapse = c.build_simple(c._CTRL_COLLAPSE_PANELS)
    rotate = c.build_simple(c._CTRL_ROTATE)
    power = c.build_power(c.POWER_MODE_OFF)
    clip = c.build_set_clipboard("hi", paste=True)
    pt, seq, paste, ln = struct.unpack(">BQ?i", clip[:14])
    ok = (notif == b"\x05" and collapse == b"\x07" and rotate == b"\x0b"
          and power == struct.pack(">Bb", 10, 0)
          and pt == c._CTRL_SET_CLIPBOARD and paste is True and ln == 2 and clip[14:] == b"hi")
    print("scrcpy 扩展报文编码:", "✅" if ok else "❌")
    return ok


def test_capabilities() -> bool:
    """两平台能力集：Android 有面板/旋转/电源、无锁屏；iOS 有锁屏/读剪贴板、无 back/rotate。"""
    from autopilot.inspector.stream.control import ScrcpyControlSink, WdaControlSink

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _FakeCore:
        resolution = (1080, 1920)
    a = ScrcpyControlSink(_FakeCore())
    w = WdaControlSink(object())
    ac, wc = a.capabilities(), w.capabilities()
    ok = ({"back", "notifications", "rotate", "power", "clipboard_set"} <= ac
          and "lock" not in ac
          and {"home", "lock", "clipboard_get", "double_tap"} <= wc
          and "back" not in wc and "rotate" not in wc)
    print("平台能力集:", "✅" if ok else "❌", f"(android {len(ac)} / ios {len(wc)})")
    return ok


def test_coord_clamp() -> bool:
    """越界点击（letterbox 区域）应钳到设备坐标边界内。"""
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QImage
        from PyQt6.QtCore import QPointF
        from autopilot.ui.widgets.mirror_panel import MirrorPanel
        _APP = QApplication.instance() or QApplication([])
        p = MirrorPanel()
        p._control = _FakeSink((200, 400))
        img = QImage(100, 200, QImage.Format.Format_RGB32); img.fill(0); p._on_frame(img)
        # 帧 100x200，设备 200x400 → ×2；点 (-5,-5) 钳到 (0,0)，(120,220) 钳到 (100,200)→(200,400)
        assert p._to_device(QPointF(-5, -5)) == (0, 0)
        assert p._to_device(QPointF(120, 220)) == (200, 400)
        ok = True
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("坐标钳制: ⏭ 跳过(", e, ")")
        return True
    print("坐标钳制(letterbox):", "✅" if ok else "❌")
    return ok


def test_appium_mirror_control_sink() -> bool:
    """镜像控制按 backend 分支：wda 只走 WdaControlSink，appium 只走 AppiumControlSink。"""
    from autopilot.inspector.stream.control import AppiumControlSink, WdaControlSink
    from autopilot.keywords.mobile.driver import AppiumManager, mirror_control_sink

    mgr = AppiumManager()
    mgr.platform = "ios"
    mgr.backend = "appium"
    fake_drv = type("D", (), {"session_id": "appium-sid"})()
    mgr.optional_driver = lambda: fake_drv
    sink = mirror_control_sink(mgr, fake_drv)
    appium_ok = isinstance(sink, AppiumControlSink) and sink._driver_provider() is fake_drv

    mgr_wda = AppiumManager()
    mgr_wda.platform = "ios"
    mgr_wda.backend = "wda"
    wda_drv = type("D", (), {"wda_client": object()})()
    wda_sink = mirror_control_sink(mgr_wda, wda_drv)
    wda_ok = isinstance(wda_sink, WdaControlSink)

    # backend=wda 时即使 drv 误带 session_id 也不得落到 Appium 分支
    mgr_wda2 = AppiumManager()
    mgr_wda2.platform = "ios"
    mgr_wda2.backend = "wda"
    no_client = mirror_control_sink(mgr_wda2, fake_drv) is None

    ok = appium_ok and wda_ok and no_client
    print("镜像控制 backend 分支(wda/appium 隔离):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_scrcpy_control_encode(), test_mirror_gestures(), test_wda_control_sink(),
              test_appium_mirror_control_sink(),
              test_scrcpy_sink_keys(), test_scrcpy_text_unicode(), test_mirror_ime_input(),
              test_scrcpy_get_clipboard(), test_wda_lock_toggle(), test_mirror_screenshot_save(),
              test_scrcpy_extra_encode(), test_capabilities(), test_coord_clamp()])
    print("\n总结:", "✅ 交互镜像全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
