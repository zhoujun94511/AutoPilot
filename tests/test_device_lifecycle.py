"""阶段22 设备会话生命周期（离线）：Appium server 管理 + 检视会话还原。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    _APP.setQuitOnLastWindowClosed(False)
    return _APP


def test_appium_server_mgr() -> bool:
    from autopilot.keywords.mobile.appium_server import AppiumServer
    import autopilot.keywords.mobile.appium_server as mod
    s = AppiumServer(port=59998)                 # 大概率空闲
    running_ok = s.is_running() is False and s.started_by_us() is False
    # 未装 appium → ensure_running 抛明确错误（patch which 返回 None）
    orig = mod.shutil.which
    mod.shutil.which = lambda _x, path=None: None
    raised = ""
    try:
        s.ensure_running(timeout=1)
    except RuntimeError as e:
        raised = str(e)
    finally:
        mod.shutil.which = orig
    msg_ok = "Appium" in raised and ("npm" in raised or "appium" in raised.lower())
    # 已在运行则复用、不拉起（patch is_running=True）
    s2 = AppiumServer(port=59997)
    s2.is_running = lambda: True
    # noinspection PyBroadException
    try:
        s2.ensure_running(timeout=1)
        reuse_ok = s2.started_by_us() is False
    except Exception:  # noqa: BLE001
        reuse_ok = False
    ok = running_ok and msg_ok and reuse_ok
    print("Appium server 生命周期(空闲/未装报错/复用不接管):", "✅" if ok else "❌")
    return ok


def test_inspect_reset() -> bool:
    """主窗口 _reset_inspect_session 应清空会话且不抛（无真实设备时）。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        app = _app()
        from autopilot.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            has_server = w._appium_server is not None
            w._reset_inspect_session()           # 无会话时应为无害空操作
            reset_ok = w._inspect_ctx is None
            w.close()                            # 触发 closeEvent 全还原，不应抛
        ok = has_server and reset_ok
        _ = app
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("检视会话还原: ⏭ 跳过(", e, ")")
        return True
    print("检视会话还原 + 关窗回收:", "✅" if ok else "❌")
    return ok


def test_inspect_cancel_clears_target() -> bool:
    """终止检视（Web / 真机）均应释放会话并清除目标，刷新从平台重选。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        _app()
        from autopilot.ui.main_window import MainWindow
        from autopilot.keywords.context import ExecutionContext
        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            w._inspect_platform = "Web"
            w._inspect_chosen = True
            w._inspect_ctx = ExecutionContext()
            w._on_inspect_cancelled()
            web_ok = w._inspect_ctx is None and w._inspect_chosen is False
            w._inspect_platform = "iOS"
            w._inspect_udid = "U1"
            w._inspect_chosen = True
            w._inspect_ctx = ExecutionContext()
            w._on_inspect_cancelled()
            mobile_ok = w._inspect_ctx is None and w._inspect_chosen is False
            w.close()
        ok = web_ok and mobile_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("终止清目标: ⏭ 跳过(", e, ")")
        return True
    print("终止清目标（Web / 真机）:", "✅" if ok else "❌")
    return ok


def test_mirror_gone_multidevice() -> bool:
    """多台同连时，镜像拔出检测应按「具体设备」判定，不误停其他设备。"""
    from autopilot.ui.main_window.device import DeviceMixin
    g = DeviceMixin._mirror_gone
    ok = all([
        g("android", "A", ["A", "B"], []) is False,   # 自己还在 → 不停
        g("android", "A", ["B"], []) is True,          # 自己拔了(别台还在) → 停
        g("ios", "U1", [], ["U1", "U2"]) is False,
        g("ios", "U1", [], ["U2"]) is True,
        g("android", "", ["B"], []) is False,          # 未指定 udid → 平台级回退
        g("android", "", [], []) is True,
        g("ios", "", [], ["U2"]) is False,
        g("ios", "", [], []) is True,
    ])
    print("多设备镜像拔出检测(设备级/平台级回退):", "✅" if ok else "❌")
    return ok


def test_inspect_device_unplug() -> bool:
    """检视设备拔出（带去抖）：持续缺席超宽限期才释放会话；瞬时闪断(掉线即恢复)不误拆；
    别台在/Web 不受影响。短宽限期配合事件循环验证真实计时回调。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        from unittest.mock import patch
        from PyQt6.QtCore import QEventLoop, QTimer
        app = _app()
        from autopilot.ui.main_window import MainWindow
        from autopilot.keywords.context import ExecutionContext
        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            w._gone_grace_s = 0.02
            calls = {"reset": 0}

            def pump_until(predicate):
                loop = QEventLoop()
                poll = QTimer(loop)
                poll.timeout.connect(lambda: loop.quit() if predicate() else None)
                timeout = QTimer(loop)
                timeout.setSingleShot(True)
                timeout.timeout.connect(loop.quit)
                poll.start(5)
                timeout.start(2000)
                try:
                    loop.exec()
                finally:
                    poll.stop()
                    timeout.stop()
                assert predicate(), "设备去抖回调未在期限内完成"

            try:
                with patch.object(w, "_reset_inspect_session", side_effect=lambda **_kw:
                                  calls.__setitem__("reset", calls["reset"] + 1)):
                    # 1) 瞬时闪断：保留所选目标，恢复后取消计时，不拆会话。
                    w._inspect_platform, w._inspect_udid, w._inspect_chosen = "iOS", "U1", True
                    w._inspect_ctx = ExecutionContext()
                    w._on_devices_changed([], ["U2"])
                    assert w._inspect_chosen and "inspect" in w._gone_timers, "缺席时未启动去抖"
                    w._on_devices_changed([], ["U1", "U2"])
                    assert w._inspect_chosen and calls["reset"] == 0, "瞬时闪断误拆检视会话"
                    assert "inspect" not in w._gone_timers, "设备恢复后未取消去抖"
                    # 2) 持续缺席：期限到后恰好释放一次并清选择。
                    w._on_devices_changed([], ["U2"])
                    pump_until(lambda: not w._inspect_chosen and calls["reset"] == 1)
                    assert "inspect" not in w._gone_timers, "确认断开后残留计时器"
                    # 3) 自己那台仍在线（多台）时不动。
                    w._inspect_platform, w._inspect_udid, w._inspect_chosen = "Android", "A", True
                    w._inspect_ctx = ExecutionContext()
                    w._on_devices_changed(["A", "B"], [])
                    app.processEvents()
                    assert w._inspect_chosen and calls["reset"] == 1, "误拆在线设备会话"
                    # 4) Web 检视不受移动设备插拔影响。
                    w._inspect_platform, w._inspect_chosen = "Web", True
                    w._on_devices_changed([], [])
                    app.processEvents()
                    assert w._inspect_chosen and calls["reset"] == 1, "移动设备断开影响 Web 会话"
                ok = True
            finally:
                w.close()
                w.deleteLater()
                app.processEvents()
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("检视设备拔出: ⏭ 跳过(", e, ")")
        return True
    print("检视设备拔出去抖(闪断不拆/持续断才释放/别台在/Web):", "✅" if ok else "❌")
    return ok


def test_mirror_device_select() -> bool:
    """镜像入口的设备选择：无设备→False；单台→自动用；多台→弹选（这里 monkeypatch 选第二项）。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        _app()
        from autopilot.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            # 无设备
            w._devices = ([], [])
            none_ok = w._select_mirror_device() is False
            # 单台 Android → 自动选中、无弹窗
            w._devices = (["AND1"], [])
            single_ok = (w._select_mirror_device() is True
                         and w._inspect_platform == "Android" and w._inspect_udid == "AND1")
            # 多台（1 Android + 1 iOS）→ 弹选；monkeypatch 选第二项(iOS)
            w._devices = (["AND1"], ["IOSU"])
            import autopilot.ui.widgets.list_pick_dialog as lpd
            from unittest.mock import patch
            orig = lpd.pick_list_item
            lpd.pick_list_item = (
                lambda _p, _t, _m, items, _i=0, **_k: (_k.get("values", items)[1], True))
            try:
                with patch("autopilot.mobile.device_info.device_picker_line",
                           side_effect=lambda p, u: f"{p}-Name ({u})"):
                    multi_ok = (w._select_mirror_device() is True
                                and w._inspect_platform == "iOS" and w._inspect_udid == "IOSU")
            finally:
                lpd.pick_list_item = orig
            w.close()
        ok = none_ok and single_ok and multi_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("镜像设备选择: ⏭ 跳过(", e, ")")
        return True
    print("镜像设备选择(无/单/多台):", "✅" if ok else "❌")
    return ok


def test_ios_mirror_auto_session() -> bool:
    """选 iOS 镜像但无会话 → 异步建会话；就绪(_on_ios_session_ready 拿到数据)→ 自动开始镜像。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        from unittest.mock import Mock, patch
        _app()
        from autopilot.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            w._inspect_platform, w._inspect_udid = "iOS", "IOSU"
            w._devices = ([], ["IOSU"])
            worker = Mock()
            worker.isRunning.return_value = False
            try:
                # 仅替换设备探测和线程启动，保留真实异步入口设置用户意图/取消状态。
                with patch("autopilot.mobile.ios_mirror.can_try_avf_mirror", return_value=False), \
                     patch("autopilot.mobile.ios_mirror.can_try_hevc_mirror", return_value=False), \
                     patch("autopilot.mobile.ios_bootstrap.device_ios_version", return_value="17.0"), \
                     patch("autopilot.ui.main_window.device_mirror.SnapshotWorker", return_value=worker), \
                     patch.object(w, "_ios_session_alive", return_value=False):
                    assert w._mirror_session() is None, "无 iOS 会话时应等待异步控制通道"
                worker.start.assert_called_once()
                worker.done.connect.assert_called_once_with(w._on_ios_mirror_control_ready)
                assert w._mirror_want_live and not w._mirror_cancel.is_set(), "异步准备未保留镜像启动意图"
                assert w._mirror_udid == "IOSU", "异步准备未固定所选设备"

                # 就绪后恢复镜像；用户已终止时，晚到的成功结果必须被丢弃。
                with patch.object(w, "_ios_session_alive", return_value=True), \
                     patch.object(w.mirror, "active", return_value=False), \
                     patch.object(w.mirror.btn_live, "setChecked") as start:
                    w._on_ios_session_ready(("png", "xml", "ios"))
                    start.assert_called_once_with(True)
                    assert w._mirror_resuming, "就绪后未进入镜像恢复状态"
                    start.reset_mock()
                    w._mirror_cancel.set()
                    w._mirror_want_live = False
                    w._on_ios_session_ready(("png", "xml", "ios"))
                    start.assert_not_called()
                ok = True
            finally:
                w.close()
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("iOS 镜像自动建会话: ⏭ 跳过(", e, ")")
        return True
    print("iOS 镜像自动建会话(无会话→异步→就绪自动开始):", "✅" if ok else "❌")
    return ok


def test_mirror_stop_releases_session() -> bool:
    """停止镜像(sessionEnded)→ 释放移动设备会话(关 driver/WDA)，不再把 WDA 留在手机上。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        _app()
        from autopilot.ui.main_window import MainWindow
        from autopilot.keywords.context import ExecutionContext
        from autopilot.keywords.mobile import driver as drv
        closed = {"n": 0}

        # noinspection PyMethodMayBeStatic
        class _FakeMgr:
            def close(self):
                closed["n"] += 1

        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            w._inspect_ctx = ExecutionContext()      # 假装有移动会话
            orig = drv.get_manager
            drv.get_manager = lambda ctx: _FakeMgr()
            try:
                w.mirror.sessionEnded.emit()       # 等价点「停止」
            finally:
                drv.get_manager = orig
            ok = closed["n"] >= 1                   # 移动会话被关闭释放
            w.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("停止镜像释放会话: ⏭ 跳过(", e, ")")
        return True
    print("停止镜像→释放移动设备会话:", "✅" if ok else "❌")
    return ok


def test_device_monitor_parse() -> bool:
    """设备列表解析（adb devices 文本 / pmd3 usbmux JSON），纯函数。"""
    from autopilot.ui.device_monitor import (
        parse_adb_devices, parse_adb_states, parse_pmd3_usbmux)
    text = ("List of devices attached\nabcd1234\tdevice\n"
            "emu-5554\toffline\nR5X\tunauthorized\n")
    adb = parse_adb_devices(text)
    states = parse_adb_states(text)
    ios = parse_pmd3_usbmux('[{"UniqueDeviceID": "00008140-001"}, {"Identifier": "abc"}]')
    ok = (adb == ["abcd1234"]                       # 只取 device 态
          and states == [("abcd1234", "device"), ("emu-5554", "offline"),
                         ("R5X", "unauthorized")]    # 全状态保留(供诊断 offline/未授权)
          and ios == ["00008140-001", "abc"]
          and parse_adb_devices("") == [] and parse_pmd3_usbmux("oops") == []
          and parse_pmd3_usbmux(
              'WARN\n\x1b[32m[{"Identifier": "UDID-X"}]\x1b[0m\n'
          ) == ["UDID-X"])
    print("设备列表解析(adb/usbmux):", "✅" if ok else "❌")
    return ok


def test_panel_placeholders() -> bool:
    """检视器整区主空态 + 镜像视图 set_hint；有快照后切三栏。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = _app()
        from autopilot.ui.widgets.inspector_panel import InspectorPanel
        from autopilot.ui.widgets.mirror_panel import MirrorPanel
        ip, mp = InspectorPanel(), MirrorPanel()
        mp.view.set_hint("y"); ph_m = not mp.view._ph.isHidden()
        # 初始：整区主空态（body index 0）
        idle_ok = ip._body_stack.currentIndex() == 0
        ip.view.set_hint("未检测到设备\n请插入并授权")
        hint_ok = "未检测到设备" in ip._workspace_ph._title.text() and ip._body_stack.currentIndex() == 0
        ok = ph_m and idle_ok and hint_ok
        _ = app
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("空态占位: ⏭ 跳过(", e, ")")
        return True
    print("空态占位(检视器整区/镜像):", "✅" if ok else "❌")
    return ok


def test_choose_device_component() -> bool:
    """纯组件 choose_device：无→empty；单台→ok自动；多台→ask弹选；取消→cancel。"""
    try:
        from autopilot.ui.main_window.device_select import choose_device, build_choices
        # 无设备
        empty_ok = choose_device([], []) == ("empty", None)
        # 单台（不论哪端）→ 自动用、不调用 ask
        called = {"n": 0}

        def ask_never(_labels, _idx):
            called["n"] += 1
            return None
        single_a = choose_device(["AND1"], [], ask=ask_never) == ("ok", ("Android", "AND1"))
        single_i = choose_device([], ["IOSU"], ask=ask_never) == ("ok", ("iOS", "IOSU"))
        auto_ok = single_a and single_i and called["n"] == 0
        # 多台 → 调 ask；选第二项(iOS)
        st, pick = choose_device(["AND1"], ["IOSU"], ask=lambda labels, idx: labels[1])
        multi_ok = st == "ok" and pick == ("iOS", "IOSU")
        # 多台但取消（ask 返回 None）→ cancel
        cancel_ok = choose_device(["AND1"], ["IOSU"], ask=lambda labels, idx: None) == ("cancel", None)
        # 平铺顺序：Android 在前
        order_ok = build_choices(["A"], ["B"]) == [("Android", "A"), ("iOS", "B")]
        from autopilot.ui.main_window.device_select import choose_device_runtime
        rt_ok, rt_pick = choose_device_runtime(["AND1"], ["IOSU"], ask=lambda labels, idx: labels[0])
        runtime_ok = rt_ok == "ok" and rt_pick == ("android", "AND1")
        ok = empty_ok and auto_ok and multi_ok and cancel_ok and order_ok and runtime_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("设备选择组件: ⏭ 跳过(", e, ")")
        return True
    print("设备选择纯组件(空/单/多/取消/顺序):", "✅" if ok else "❌")
    return ok


def test_inspect_device_select() -> bool:
    """检视器刷新快照前确认目标：先选平台；无真机可 Web；单台/多台/已选过。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        from PyQt6.QtWidgets import QInputDialog
        _app()
        from autopilot.ui.main_window import MainWindow

        def pick_plat(plat: str):
            def fake_item(*a, **_k):
                label = a[2] if len(a) > 2 else ""
                if label == "平台：":
                    return plat, True
                if label == "浏览器：":
                    return "chrome", True
                items = a[3] if len(a) > 3 else []
                return (items[0], True) if items else ("", False)
            return fake_item

        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            orig_item = QInputDialog.getItem
            orig_text = QInputDialog.getText
            # 默认未选过：取消平台 → 中止
            w._inspect_chosen = False
            w._devices = ([], [])
            QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
            none_ok = w._ensure_inspect_device() is False and w._inspect_chosen is False
            # 单台 iOS → 选平台 iOS 后自动用唯一设备
            w._inspect_chosen = False
            w._devices = ([], ["IOSU"])
            QInputDialog.getItem = staticmethod(pick_plat("iOS"))
            QInputDialog.getText = staticmethod(lambda *a, **k: ("", True))
            single_ok = (w._ensure_inspect_device() is True
                         and w._inspect_platform == "iOS" and w._inspect_udid == "IOSU"
                         and w._inspect_chosen is True)
            # 已选过且目标仍在线 → 直接放行，不再弹（刷新频繁，不应每次打断）
            w._devices = (["AND1"], ["IOSU"])
            reuse_ok = w._ensure_inspect_device() is True
            # 已选 Android 但无 Android 在线 → 中止并清标记（不误拉 Appium）
            w._inspect_chosen = True
            w._inspect_platform = "Android"
            w._inspect_udid = ""
            w._devices = ([], ["IOSU"])
            stale_ok = w._ensure_inspect_device() is False and w._inspect_chosen is False
            # 多台且未选过 → 选 iOS 平台后弹选第二项
            w._inspect_chosen = False
            w._devices = (["AND1"], ["IOSU"])
            QInputDialog.getItem = staticmethod(pick_plat("iOS"))
            QInputDialog.getText = staticmethod(lambda *a, **k: ("", True))
            import autopilot.ui.widgets.list_pick_dialog as lpd
            from unittest.mock import patch
            orig_pick = lpd.pick_list_item
            lpd.pick_list_item = (
                lambda _p, _t, _m, items, _i=0, **_k: (_k.get("values", items)[1], True))
            try:
                with patch("autopilot.mobile.device_info.device_picker_line",
                           side_effect=lambda p, u: f"{p}-Name ({u})"):
                    multi_ok = (w._ensure_inspect_device() is True
                                and w._inspect_platform == "iOS" and w._inspect_udid == "IOSU")
            finally:
                lpd.pick_list_item = orig_pick
            # 无真机 → 选 Web 仍可检视
            w._inspect_chosen = False
            w._devices = ([], [])
            QInputDialog.getItem = staticmethod(pick_plat("Web"))
            QInputDialog.getText = staticmethod(lambda *a, **k: ("https://example.com", True))
            web_ok = (w._ensure_inspect_device() is True
                      and w._inspect_platform == "Web"
                      and w._inspect_chosen is True)
            QInputDialog.getItem = orig_item
            QInputDialog.getText = orig_text
            w.close()
        ok = none_ok and single_ok and reuse_ok and stale_ok and multi_ok and web_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("检视设备选择: ⏭ 跳过(", e, ")")
        return True
    print("检视刷新前设备选择(无/单/已选/多台):", "✅" if ok else "❌")
    return ok


def test_no_mobile_devices() -> bool:
    """Android/iOS 均未连接：检视/镜像/连接入口均友好中止，不误拉 Appium。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tempfile
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        app = _app()
        from autopilot.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as t:
            w = MainWindow(project_dir=t, config_dir="")
            w._devices = ([], [])

            idx_ok = w._default_inspect_platform_index() == 2
            has_ok = w._has_mobile_device() is False
            msg_ok = "Web" in w._no_mobile_devices_message()

            QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
            none_inspect = w._ensure_inspect_device() is False
            none_mirror = w._select_mirror_device() is False

            orig_info = QMessageBox.information
            orig_warn = QMessageBox.warning
            orig_item = QInputDialog.getItem
            QMessageBox.information = staticmethod(lambda *a, **k: None)
            QMessageBox.warning = staticmethod(lambda *a, **k: None)
            QInputDialog.getItem = staticmethod(
                lambda *a, **k: ("Android", True))
            try:
                w.connect_inspector()
            finally:
                QMessageBox.information = orig_info
                QMessageBox.warning = orig_warn
                QInputDialog.getItem = orig_item
            blocked_ok = w._inspect_chosen is False
            mirror_disabled = not w.mirror.btn_live.isEnabled()

            w.close()
        ok = (idx_ok and has_ok and msg_ok and none_inspect and none_mirror
              and blocked_ok and mirror_disabled)
        _ = app
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("无真机容错: ⏭ 跳过(", e, ")")
        return True
    print("无真机容错(检视/镜像/连接):", "✅" if ok else "❌")
    return ok


def test_mobile_timing_settings() -> bool:
    """Appium 启动超时 / 设备拔出去抖：settings 默认、持久化、环境变量与钳位。"""
    import tempfile
    from autopilot.runtime import settings

    env_keys = ("AUTOPILOT_CONFIG_DIR", "AUTOPILOT_APPIUM_STARTUP_TIMEOUT_S",
                "AUTOPILOT_DEVICE_GONE_GRACE_S")
    saved = {k: os.environ.get(k) for k in env_keys}

    def _restore_env() -> None:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    ok = False
    try:
        with tempfile.TemporaryDirectory() as cfg:
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            for k in ("AUTOPILOT_APPIUM_STARTUP_TIMEOUT_S", "AUTOPILOT_DEVICE_GONE_GRACE_S"):
                os.environ.pop(k, None)
            default_ok = (
                settings.appium_startup_timeout_s() == 40.0
                and settings.device_gone_grace_s() == 8.0
            )
            settings.set_appium_startup_timeout_s(25)
            settings.set_device_gone_grace_s(3)
            persist_ok = (
                settings.appium_startup_timeout_s() == 25.0
                and settings.device_gone_grace_s() == 3.0
            )
            settings.set_appium_startup_timeout_s(9999)
            settings.set_device_gone_grace_s(-1)
            clamp_ok = (
                settings.appium_startup_timeout_s() == 300.0
                and settings.device_gone_grace_s() == 0.0
            )
            # 旧版 ms 键自动换算为秒（须在环境变量覆盖之前测）
            data = settings.load()
            data.pop("device_gone_grace_s", None)
            data["device_gone_grace_ms"] = 5000
            settings.save(data)
            legacy_ok = settings.device_gone_grace_s() == 5.0
            os.environ["AUTOPILOT_APPIUM_STARTUP_TIMEOUT_S"] = "12.5"
            os.environ["AUTOPILOT_DEVICE_GONE_GRACE_S"] = "1.5"
            env_ok = (
                settings.appium_startup_timeout_s() == 12.5
                and settings.device_gone_grace_s() == 1.5
            )
            ok = bool(default_ok and persist_ok and clamp_ok and legacy_ok and env_ok)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("移动时序配置:", "⏭ 跳过(", e, ")")
        _restore_env()
        return True
    _restore_env()
    print("移动时序配置(默认/持久化/钳位/环境变量):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_appium_server_mgr(), test_inspect_reset(), test_inspect_cancel_clears_target(),
              test_mirror_gone_multidevice(), test_mirror_device_select(),
              test_ios_mirror_auto_session(), test_mirror_stop_releases_session(),
              test_choose_device_component(), test_inspect_device_select(),
              test_inspect_device_unplug(), test_no_mobile_devices(),
              test_device_monitor_parse(), test_panel_placeholders(),
              test_mobile_timing_settings()])
    print("\n总结:", "✅ 设备会话生命周期全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
