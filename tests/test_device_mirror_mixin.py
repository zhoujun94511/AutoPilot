"""IDE device_mirror 切片：DeviceMixin 继承 DeviceMirrorMixin，镜像方法可解析。"""

from __future__ import annotations

import threading
from typing import cast


def test_device_mixin_inherits_mirror_mixin():
    from autopilot.ui.main_window.device import DeviceMixin
    from autopilot.ui.main_window.device_mirror import DeviceMirrorMixin

    assert issubclass(DeviceMixin, DeviceMirrorMixin)
    for name in (
        "_prepare_mirror_start",
        "_mirror_session",
        "_on_mirror_video_failed",
        "_on_mirror_stopped",
        "_select_mirror_device",
    ):
        assert hasattr(DeviceMixin, name)
        assert hasattr(DeviceMirrorMixin, name)
    # 检视仍在 device.py
    assert hasattr(DeviceMixin, "_inspector_snapshot")
    assert not hasattr(DeviceMirrorMixin, "_inspector_snapshot")


def test_pending_ios_mirror_is_cancelled_when_bound_device_disappears():
    """WDA 尚在准备时镜像未 active，也必须按固定 UDID 取消旧设备任务。"""
    from autopilot.ui.main_window.device_mirror import DeviceMirrorMixin

    events: list[tuple[str, str]] = []

    _Label = type(
        "_Label",
        (),
        {"setText": staticmethod(lambda text: events.append(("label", text)))},
    )

    class _View:
        @staticmethod
        def set_hint(text):
            events.append(("hint", text))

    class _Mirror:
        lbl = _Label()
        view = _View()

        @staticmethod
        def active():
            return False

        @staticmethod
        def platform_name():
            return ""

    class _Console:
        @staticmethod
        def log(message, _tag, _level):
            events.append(("log", message))

    class _Harness:
        mirror = _Mirror()
        console = _Console()
        _devices = ([], ["NEW-UDID"])
        _mirror_udid = "OLD-UDID"
        _mirror_control_pending = True
        _mirror_want_live = True
        _mirror_cancel = threading.Event()

        @staticmethod
        def _mirror_gone(platform, udid, _android, ios):
            return platform == "ios" and udid not in ios

    harness = cast(DeviceMirrorMixin, _Harness())
    DeviceMirrorMixin._on_mirror_device_gone(harness)

    assert harness._mirror_cancel.is_set()
    assert harness._mirror_control_pending is False
    assert harness._mirror_want_live is False
    assert "设备已断开或已切换" in getattr(harness, "_mirror_control_error")
    assert any(kind == "hint" and "重新点「开始」" in text for kind, text in events)


def test_successful_worker_result_is_not_probed_twice():
    """worker 已完成探活，UI 提交阶段不得再次用破坏性探针拆掉新会话。"""
    from autopilot.ui.main_window.device_mirror import DeviceMirrorMixin

    checked: list[bool] = []

    _Button = type(
        "_Button",
        (),
        {"setChecked": staticmethod(lambda value: checked.append(value))},
    )

    class _Mirror:
        btn_live = _Button()

        @staticmethod
        def active():
            return False

    class _Console:
        @staticmethod
        def log(*_args):
            return None

    class _Harness:
        mirror = _Mirror()
        console = _Console()
        _mirror_control_pending = True
        _mirror_fallback_mjpeg = False
        _mirror_want_live = True
        _mirror_cancel = threading.Event()

        @staticmethod
        def _ios_session_alive():
            raise AssertionError("UI 提交阶段发生了重复 iOS 会话探活")

    harness = cast(DeviceMirrorMixin, _Harness())
    DeviceMirrorMixin._on_ios_mirror_control_ready(harness, True)

    assert harness._mirror_control_pending is False
    assert getattr(harness, "_mirror_resuming") is True
    assert checked == [True]
