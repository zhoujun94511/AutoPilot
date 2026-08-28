"""iOS 端口转发参数兼容、iOS 后端可用性与采页稳定等待。

真机实测：pymobiledevice3 4.x 的 ``usbmux forward`` 已把 ``--udid`` 换成
``--serial``，误传会直接退出，表现成「WDA /status 未就绪」；同时 Windows 宿主
可用 WDA-direct 跑 iOS，不该被判成无可用后端。
"""

from __future__ import annotations

import subprocess

import autopilot.mobile.ios_bootstrap as ib
from autopilot.authoring.capture import capture_settled_ui_context
from autopilot.mgmt import local_devices


class _Help:
    """产品侧禁用 text=True（Windows GBK 会崩解码线程），故桩也必须返回 bytes。"""

    def __init__(self, text: str) -> None:
        self.stdout = text.encode("utf-8")
        self.stderr = b""
        self.returncode = 0


def _patch_help(monkeypatch, text: str) -> None:
    ib.pmd3_forward_device_flag.cache_clear()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Help(text))


def test_forward_uses_serial_on_new_pymobiledevice3(monkeypatch):
    _patch_help(monkeypatch, "Options:\n  --serial TEXT device serial number\n")
    cmd = ib.pmd3_forward_cmd(8100, 8100, udid="UDID-1")
    assert cmd[-2:] == ["--serial", "UDID-1"]
    assert cmd[1:5] == ["-m", "pymobiledevice3", "usbmux", "forward"]
    ib.pmd3_forward_device_flag.cache_clear()


def test_forward_falls_back_to_udid_on_legacy(monkeypatch):
    _patch_help(monkeypatch, "Options:\n  --udid TEXT device udid\n")
    assert ib.pmd3_forward_cmd(9100, 9100, udid="UDID-1")[-2:] == ["--udid", "UDID-1"]
    ib.pmd3_forward_device_flag.cache_clear()


def test_forward_flag_defaults_to_serial_when_help_unavailable(monkeypatch):
    ib.pmd3_forward_device_flag.cache_clear()

    def boom(*_a, **_kw):
        raise OSError("no interpreter")

    monkeypatch.setattr(subprocess, "run", boom)
    assert ib.pmd3_forward_device_flag() == "--serial"
    ib.pmd3_forward_device_flag.cache_clear()


def test_ios_backend_available_on_windows(monkeypatch):
    monkeypatch.setattr("autopilot.mobile.ios_devices.ios_tooling_available", lambda: True)
    monkeypatch.setattr(local_devices.platform, "system", lambda: "Windows")
    assert local_devices._ios_host_backends(has_appium=True) == ["ios-wda"]


def test_ios_backend_includes_appium_on_mac(monkeypatch):
    monkeypatch.setattr("autopilot.mobile.ios_devices.ios_tooling_available", lambda: True)
    monkeypatch.setattr(local_devices.platform, "system", lambda: "Darwin")
    assert local_devices._ios_host_backends(has_appium=True) == ["ios-wda", "ios-appium"]
    assert local_devices._ios_host_backends(has_appium=False) == ["ios-wda"]


def test_ios_backend_empty_without_tooling(monkeypatch):
    monkeypatch.setattr("autopilot.mobile.ios_devices.ios_tooling_available", lambda: False)
    assert local_devices._ios_host_backends(has_appium=True) == []


def test_settled_capture_skips_splash(monkeypatch):
    """启动页本身也是静止的：仅靠「两次相同」会把启动页当成首页。"""
    frames = [
        {"element_count": 3, "elements_text": "[splash]"},
        {"element_count": 3, "elements_text": "[splash]"},
        {"element_count": 28, "elements_text": "[home]"},
        {"element_count": 28, "elements_text": "[home]"},
    ]
    seen = {"i": 0}

    def fake_capture(_ctx, _platform, **_kw):
        idx = min(seen["i"], len(frames) - 1)
        seen["i"] += 1
        return dict(frames[idx])

    clock = {"t": 0.0}
    monkeypatch.setattr("autopilot.authoring.capture.capture_ui_context", fake_capture)
    monkeypatch.setattr("autopilot.authoring.capture.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        "autopilot.authoring.capture.time.sleep",
        lambda sec: clock.__setitem__("t", clock["t"] + sec),
    )

    cap = capture_settled_ui_context(object(), "ios", min_wait=4.5, timeout=15.0)
    assert cap["elements_text"] == "[home]"


def test_settled_capture_returns_last_on_timeout(monkeypatch):
    def fake_capture(_ctx, _platform, **_kw):
        return {"element_count": 1, "elements_text": "[busy]"}

    clock = {"t": 0.0}
    monkeypatch.setattr("autopilot.authoring.capture.capture_ui_context", fake_capture)
    monkeypatch.setattr("autopilot.authoring.capture.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        "autopilot.authoring.capture.time.sleep",
        lambda sec: clock.__setitem__("t", clock["t"] + sec),
    )
    cap = capture_settled_ui_context(object(), "ios", min_wait=100.0, timeout=3.0)
    assert cap["elements_text"] == "[busy]"
