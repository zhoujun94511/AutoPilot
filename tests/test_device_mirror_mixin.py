"""IDE device_mirror 切片：DeviceMixin 继承 DeviceMirrorMixin，镜像方法可解析。"""

from __future__ import annotations


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
