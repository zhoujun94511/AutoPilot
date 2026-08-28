"""客户端 Runner 契约：后端匹配（与 Platform 对齐，无服务端 import）。"""

from __future__ import annotations

from autopilot.runner.contract import (
    BACKEND_ANDROID_APPIUM,
    BACKEND_IOS_APPIUM,
    BACKEND_IOS_WDA,
    DeviceInfo,
    HeartbeatIn,
    backends_ok,
    required_backends,
)


def test_required_backends_mapping():
    assert required_backends("android", "auto") is None
    assert required_backends("android", "uia2") == {BACKEND_ANDROID_APPIUM}
    assert required_backends("ios", "wda") == {BACKEND_IOS_WDA}
    assert required_backends("ios", "appium") == {BACKEND_IOS_APPIUM}


def test_backends_ok_intersection():
    assert backends_ok(
        [BACKEND_ANDROID_APPIUM],
        platform="android",
        backend_mode="uia2",
    )
    assert not backends_ok(
        [BACKEND_IOS_WDA],
        platform="android",
        backend_mode="uia2",
    )


def test_dry_probe_importable():
    from autopilot.runner.devices import format_probe_report

    text = format_probe_report()
    assert "host capabilities" in text
    assert "devices" in text


def test_heartbeat_contract_always_serializes_full_inventory():
    inventory = [DeviceInfo(udid="A", platform="android")]
    body = HeartbeatIn(
        runner_id="contract-r1",
        inventory=inventory,
        devices=inventory,
        policy_revision=2,
    ).to_dict()
    assert body["inventory"] == body["devices"]
    assert body["policy_revision"] == 2
