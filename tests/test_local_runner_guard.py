"""本机 Runner ↔ 检视/镜像：确认文案与摘除策略（不硬互斥）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from autopilot.mgmt.local_devices import LocalDevice
from autopilot.mgmt.local_runner_guard import (
    ACTION_CANCEL,
    ACTION_EXCLUDE,
    ACTION_REPORT_ALL,
    KIND_INSPECT,
    KIND_MIRROR,
    SCENARIO_OPEN_INSPECT,
    SCENARIO_START_MULTI,
    SCENARIO_START_SINGLE,
    bound_mobile_udid,
    collect_local_udids,
    inspect_kind,
    open_inspect_prompt,
    resolve_prompt_action,
    start_runner_prompt,
)


def test_bound_mobile_udid_skips_web():
    assert bound_mobile_udid(platform="Web", udid="http://x") == ""
    assert bound_mobile_udid(platform="Android", udid="  A1  ") == "A1"
    assert bound_mobile_udid(platform="ios", udid="U1") == "U1"
    assert bound_mobile_udid(platform="Android", udid="") == ""


def test_inspect_kind_mirror_wins_over_inspect():
    assert inspect_kind(mirror_active=True, inspect_chosen=True, udid="A") == KIND_MIRROR
    assert inspect_kind(inspect_ctx=object(), udid="A") == KIND_INSPECT
    assert inspect_kind(inspect_chosen=True, udid="A") == KIND_INSPECT
    assert inspect_kind(inspect_chosen=False, udid="A") == ""
    assert inspect_kind(inspect_chosen=True, udid="") == ""


def test_collect_local_udids_dedupes():
    assert collect_local_udids(
        ["A", "B"],
        ["B"],
        [LocalDevice(udid="C", platform="ios"), SimpleNamespace(udid="A")],
    ) == ["A", "B", "C"]


def test_start_runner_prompt_none_without_inspect():
    assert start_runner_prompt(
        inspect_udid="", inspect_kind_label=KIND_INSPECT, local_udids=["A"]
    ) is None


def test_start_runner_prompt_multi_defaults_exclude():
    prompt = start_runner_prompt(
        inspect_udid="PHONE-1",
        inspect_kind_label=KIND_INSPECT,
        local_udids=["PHONE-1", "PHONE-2"],
    )
    assert prompt is not None
    assert prompt.scenario == SCENARIO_START_MULTI
    assert "PHONE-1" in prompt.text
    assert "摘除" in prompt.text
    assert prompt.yes_text == "启动并摘除该机"
    assert prompt.no_text == "仍上报全部"
    assert prompt.default_action == ACTION_EXCLUDE
    assert resolve_prompt_action(prompt.scenario, "yes") == ACTION_EXCLUDE
    assert resolve_prompt_action(prompt.scenario, "no") == ACTION_REPORT_ALL
    assert resolve_prompt_action(prompt.scenario, "cancel") == ACTION_CANCEL


def test_start_runner_prompt_single_warns_but_allows():
    prompt = start_runner_prompt(
        inspect_udid="ONLY-1",
        inspect_kind_label=KIND_MIRROR,
        local_udids=["ONLY-1"],
    )
    assert prompt is not None
    assert prompt.scenario == SCENARIO_START_SINGLE
    assert "镜像" in prompt.text
    assert prompt.yes_text == "仍然启动"
    assert not prompt.no_text
    assert prompt.default_action == ACTION_CANCEL
    assert resolve_prompt_action(prompt.scenario, "yes") == ACTION_REPORT_ALL
    assert resolve_prompt_action(prompt.scenario, "cancel") == ACTION_CANCEL


def test_open_inspect_prompt_only_when_runner_reports_udid():
    assert open_inspect_prompt(
        runner_running=False, reports_udid=True, udid="A", kind="检视"
    ) is None
    assert open_inspect_prompt(
        runner_running=True, reports_udid=False, udid="A", kind="检视"
    ) is None
    prompt = open_inspect_prompt(
        runner_running=True, reports_udid=True, udid="A", kind="镜像"
    )
    assert prompt is not None
    assert prompt.scenario == SCENARIO_OPEN_INSPECT
    assert prompt.yes_text == "继续并摘除上报"
    assert prompt.no_text == "继续且保持上报"
    assert "镜像" in prompt.text
    assert resolve_prompt_action(prompt.scenario, "yes") == ACTION_EXCLUDE
    assert resolve_prompt_action(prompt.scenario, "no") == ACTION_REPORT_ALL


@pytest.mark.parametrize(
    ("clicked", "want"),
    [("yes", ACTION_EXCLUDE), ("no", ACTION_REPORT_ALL), ("", ACTION_CANCEL)],
)
def test_resolve_prompt_action_open_inspect(clicked, want):
    assert resolve_prompt_action(SCENARIO_OPEN_INSPECT, clicked) == want


def test_exclude_roundtrip_and_heartbeat_sync(tmp_path, monkeypatch):
    from autopilot.runner.contract import DeviceInfo
    from autopilot.runner.device_policy import (
        add_exclude_udids,
        load_device_policy,
        remove_exclude_udids,
        sync_exclude_udids,
        DevicePolicy,
    )

    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path))
    rid = "ide-guard-r1"
    add_exclude_udids(rid, {"VIS-1"})
    policy = load_device_policy(rid)
    inventory = [
        DeviceInfo(udid="VIS-1", platform="ios"),
        DeviceInfo(udid="OTH-2", platform="android"),
    ]
    assert [d.udid for d in policy.filter(inventory)] == ["OTH-2"]

    memory = DevicePolicy(mode="all")
    synced = sync_exclude_udids(rid, memory)
    assert synced.exclude_udids == {"VIS-1"}
    assert [d.udid for d in synced.filter(inventory)] == ["OTH-2"]

    remove_exclude_udids(rid, {"VIS-1"})
    assert load_device_policy(rid).exclude_udids == set()
