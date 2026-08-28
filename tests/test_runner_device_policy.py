"""IDE Runner 的设备策略过滤与断网缓存。"""
from __future__ import annotations

from typing import cast

from autopilot.runner.agent import RunnerAgent
from autopilot.runner.client import PlatformClient
from autopilot.runner.contract import DeviceInfo


class _PolicyClient:
    def __init__(self):
        self.bodies = []

    def heartbeat(self, body):
        self.bodies.append(body)
        return {
            "device_selection_mode": "include",
            "selected_device_udids": ["A"],
            "device_policy_revision": 2,
        }


def test_ide_runner_reports_inventory_but_filters_devices_and_reloads_cache(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    devices = [
        DeviceInfo(udid="A", platform="android"),
        DeviceInfo(udid="B", platform="android"),
    ]
    monkeypatch.setattr(
        "autopilot.runner.agent.list_local_devices", lambda: list(devices)
    )
    monkeypatch.setattr(
        "autopilot.runner.agent.probe_host_capabilities", lambda: ([], [])
    )
    stub = _PolicyClient()
    client = cast(PlatformClient, stub)
    agent = RunnerAgent("http://platform", runner_id="ide-policy-r1")
    agent._heartbeat_once(client)
    assert [d.udid for d in stub.bodies[0].inventory] == ["A", "B"]
    assert [d.udid for d in stub.bodies[0].devices] == ["A", "B"]

    agent._heartbeat_once(client)
    assert [d.udid for d in stub.bodies[1].inventory] == ["A", "B"]
    assert [d.udid for d in stub.bodies[1].devices] == ["A"]

    # 新进程在 Platform 不可达前已从磁盘恢复最近策略。
    restarted = RunnerAgent("http://platform", runner_id="ide-policy-r1")
    assert restarted._device_policy.revision == 2
    assert restarted._device_policy.selected_udids == {"A"}


def test_ide_policy_revision_does_not_roll_back(tmp_path, monkeypatch):
    from autopilot.runner.device_policy import DevicePolicy, update_device_policy

    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    current = DevicePolicy(mode="include", selected_udids={"A"}, revision=4)
    kept = update_device_policy(
        "ide-rev-r1",
        current,
        {
            "device_selection_mode": "all",
            "selected_device_udids": ["A", "B"],
            "device_policy_revision": 1,
        },
    )
    assert kept.revision == 4
    assert kept.mode == "include"
    assert kept.selected_udids == {"A"}


def test_ide_heartbeat_payload_matches_platform_filter_contract(tmp_path, monkeypatch):
    """同一策略下 inventory 全量、devices 仅 allowlist，字段与 Platform Agent 一致。"""
    from autopilot.runner.contract import HeartbeatIn
    from autopilot.runner.device_policy import DevicePolicy

    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    inventory = [
        DeviceInfo(udid="A", platform="android"),
        DeviceInfo(udid="B", platform="android"),
        DeviceInfo(udid="C", platform="ios"),
    ]
    policy = DevicePolicy(mode="include", selected_udids={"A", "C"}, revision=7)
    payload = HeartbeatIn(
        runner_id="dual-r1",
        devices=policy.filter(inventory),
        inventory=inventory,
        policy_revision=policy.revision,
    ).to_dict()
    assert [d["udid"] for d in payload["inventory"]] == ["A", "B", "C"]
    assert [d["udid"] for d in payload["devices"]] == ["A", "C"]
    assert payload["policy_revision"] == 7


def test_ide_exclude_survives_platform_policy_update(tmp_path, monkeypatch):
    from autopilot.runner.device_policy import (
        DevicePolicy,
        add_exclude_udids,
        policy_would_report,
        update_device_policy,
    )

    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    add_exclude_udids("ide-ex-r1", {"B"})
    current = DevicePolicy(mode="all", revision=1, exclude_udids={"B"})
    updated = update_device_policy(
        "ide-ex-r1",
        current,
        {
            "device_selection_mode": "include",
            "selected_device_udids": ["A", "B"],
            "device_policy_revision": 3,
        },
    )
    assert updated.mode == "include"
    assert updated.selected_udids == {"A", "B"}
    assert updated.exclude_udids == {"B"}
    inventory = [
        DeviceInfo(udid="A", platform="android"),
        DeviceInfo(udid="B", platform="android"),
    ]
    assert [d.udid for d in updated.filter(inventory)] == ["A"]
    assert policy_would_report(updated, "A")
    assert not policy_would_report(updated, "B")


def test_ide_heartbeat_applies_disk_exclude_same_tick(tmp_path, monkeypatch):
    from autopilot.runner.device_policy import add_exclude_udids

    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    devices = [
        DeviceInfo(udid="VIS", platform="ios"),
        DeviceInfo(udid="OTH", platform="android"),
    ]
    monkeypatch.setattr(
        "autopilot.runner.agent.list_local_devices", lambda: list(devices)
    )
    monkeypatch.setattr(
        "autopilot.runner.agent.probe_host_capabilities", lambda: ([], [])
    )

    class _HbClient:
        def __init__(self):
            self.bodies = []

        def heartbeat(self, body):
            self.bodies.append(body)
            return {"device_policy_revision": 0}

    add_exclude_udids("ide-hb-ex", {"VIS"})
    agent = RunnerAgent("http://platform", runner_id="ide-hb-ex")
    hb_stub = _HbClient()
    client = cast(PlatformClient, hb_stub)
    agent._heartbeat_once(client)
    assert [d.udid for d in hb_stub.bodies[0].inventory] == ["VIS", "OTH"]
    assert [d.udid for d in hb_stub.bodies[0].devices] == ["OTH"]
