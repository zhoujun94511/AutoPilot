"""iOS 设备枚举的健壮性：任何失败都要留痕，且不能被读成「没插设备」。

设备插拔监测走进程内 usbmux，编写/批跑链路走 pymobiledevice3 CLI。两条通道的结论必须
一致，否则会出现「设备面板看得见、AI 编写却说没检测到设备」。
"""

from __future__ import annotations

import subprocess

import pytest

from autopilot.mobile import ios_devices as iosd


@pytest.fixture(autouse=True)
def _clear_tool_errors():
    tool_errors = getattr(iosd, "_TOOL_ERRORS")
    tool_errors.clear()
    yield
    tool_errors.clear()


def _fake_run(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    def run(cmd, **kwargs):
        assert "text" not in kwargs, "必须自行解码，text=True 在 GBK 控制台会抛 UnicodeDecodeError"
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    return run


def test_parse_tolerates_log_noise_around_json():
    devices = iosd._parse_pmd3('WARN boot\n[{"Identifier": "ABC-123"}]\ntail\n')
    assert [d.udid for d in devices] == ["ABC-123"]


def test_parse_strips_ansi_color_codes():
    """click/rich 颜色码不得再让 JSON 解析失败（日志里曾出现尾部 \\x1b[0m）。"""
    colored = '\x1b[32m[{"Identifier": "ABC-123"}]\x1b[0m\n'
    assert [d.udid for d in iosd._parse_pmd3(colored)] == ["ABC-123"]
    assert iosd.strip_ansi("\x1b[0m").strip() == ""


def test_parse_goios_jsonl_device_list():
    """go-ios 在 Windows 上常先打 JSON warning，再打 deviceList。"""
    text = (
        '{"level":"warning","msg":"go-ios agent is not running.","time":"2026-08-24T16:09:00+08:00"}\n'
        '{"deviceList":["00008140-0010000000000001","00008130-0010000000000002"]}\n'
    )
    assert [d.udid for d in iosd._parse_goios_list(text)] == [
        "00008140-0010000000000001",
        "00008130-0010000000000002",
    ]


def test_goios_list_never_uses_text_mode(monkeypatch):
    """含非 GBK 字节的 stdout 在 text=True 下会炸 _readerthread；必须自行 utf-8 解码。"""
    # 设备名含中文时 go-ios 输出为 UTF-8；0x80 一类字节在 GBK 下非法
    payload = "00008140-0010000000000001 \xe6\xb5\x8b\xe8\xaf\x95\xe6\x9c\xba\n"

    def fake_run(cmd, **kwargs):
        assert "text" not in kwargs
        assert kwargs.get("env", {}).get("NO_COLOR") == "1"
        return subprocess.CompletedProcess(cmd, 0, payload.encode("utf-8"), b"")

    monkeypatch.setattr(
        "autopilot.mobile.ios_bootstrap.resolve_go_ios",
        lambda: "ios.exe",
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    devices = iosd._list_via_goios()
    assert [d.udid for d in devices] == ["00008140-0010000000000001"]


def test_parse_falls_back_to_udid_text_when_not_json():
    """新版 CLI 若改成表格输出，仍要能取到 UDID 而不是当成没设备。"""
    devices = iosd._parse_pmd3("Identifier: 00008140-0010000000000001  name: iPhone")
    assert [d.udid for d in devices] == ["00008140-0010000000000001"]


def test_undecodable_output_does_not_lose_devices(monkeypatch):
    """非法字节不得让枚举抛 UnicodeDecodeError（会被上层吞成空列表）。"""
    payload = b'\xff\xfe[{"Identifier": "UDID-1"}]'
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))
    assert [d.udid for d in iosd._list_via_pymobiledevice3()] == ["UDID-1"]


def test_unparsable_success_output_records_reason(monkeypatch):
    """退出码 0 但解析不出设备：必须留痕，否则提示会误导成「没插设备」。"""
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=b"Devices:\n  (none parsed)"))
    assert iosd._list_via_pymobiledevice3() == []
    assert "无法解析" in iosd.ios_tooling_error()


def test_clean_empty_output_keeps_error_clear(monkeypatch):
    """真的没插设备时不该伪造工具链故障。"""
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=b""))
    assert iosd._list_via_pymobiledevice3() == []
    assert iosd.ios_tooling_error() == ""


def test_inproc_usbmux_rescues_failing_cli(monkeypatch):
    """CLI 挂掉时用监测同款进程内通道兜底，避免两条链路结论不一致。"""
    monkeypatch.setattr(iosd, "_list_via_pymobiledevice3", lambda **kw: [])
    monkeypatch.setattr(
        iosd,
        "_list_via_usbmux_inproc",
        lambda: [iosd.IosUsbDevice(udid="UDID-9", name="iPhone", product_type="", ios_version="")],
    )
    monkeypatch.setattr(iosd, "_list_via_goios", lambda: [])
    assert [d.udid for d in iosd.list_usb_devices(retries=0)] == ["UDID-9"]


def test_cli_metadata_wins_over_inproc(monkeypatch):
    """CLI 能用时优先用它：进程内通道拿不到型号/系统版本。"""
    rich = iosd.IosUsbDevice(
        udid="UDID-9", name="iPhone", product_type="iPhone17,5", ios_version="26.6"
    )
    monkeypatch.setattr(iosd, "_list_via_pymobiledevice3", lambda **kw: [rich])
    monkeypatch.setattr(
        iosd,
        "_list_via_usbmux_inproc",
        lambda: [iosd.IosUsbDevice(udid="UDID-9", name="iPhone", product_type="", ios_version="")],
    )
    assert iosd.list_usb_devices(retries=0)[0].ios_version == "26.6"


def test_mgmt_wrapper_records_enumeration_failure(monkeypatch):
    """mgmt 层原先静默 return []，上层只能看到「没插设备」。"""
    from autopilot.mgmt import local_devices

    def boom():
        raise RuntimeError("usbmux 连接被拒绝")

    monkeypatch.setattr(iosd, "list_usb_devices", boom)
    assert local_devices.list_ios_devices() == []
    assert "usbmux 连接被拒绝" in iosd.ios_tooling_error()


def test_mgmt_wrapper_reports_ios_marketing_model(monkeypatch):
    """IDE 私有 Runner 上报前应把 ProductType 转成用户可识别的市场型号。"""
    from autopilot.mgmt import local_devices

    raw = iosd.IosUsbDevice(
        udid="UDID-15PM",
        name="iPhone",
        product_type="iPhone16,2",
        ios_version="18.6.2",
    )
    monkeypatch.setattr(iosd, "list_usb_devices", lambda: [raw])
    monkeypatch.setattr(local_devices, "_host_backends", lambda: ["ios-wda"])

    device = local_devices.list_ios_devices()[0]
    assert device.name == "iPhone"
    assert device.model == "iPhone 15 Pro Max"
