"""本机 Runner ↔ 检视/镜像 — 白盒链路。

对照「同一 UDID 确认 + exclude 摘除、不硬互斥」的落地，从纯逻辑到 Mixin
入口再到心跳过滤做链路验证。不改 Platform busy / claim。

功能需求 (FR)
-------------
FR-LR-01  无检视/镜像绑定时启动本机 Runner 不弹确认
FR-LR-02  多机 + 已绑真机：启动确认默认摘除该 UDID，再拉起进程
FR-LR-03  单机强提示仍可启动，不写 exclude
FR-LR-04  启动确认取消则不 start
FR-LR-05  开检视时 Runner 已上报该 UDID：确认后写入 exclude
FR-LR-06  该机已在 exclude 中：开检视/镜像不再弹框
FR-LR-07  「继续且保持上报」仍提交目标，不写 exclude
FR-LR-08  开检视取消：不提交；已有绑定则恢复旧 UDID
FR-LR-09  Web 检视不走 USB 确认
FR-LR-10  终止检视 / 设备离线：把该机放回上报
FR-LR-11  exclude 落盘后同一拍心跳 devices 不含该机，inventory 仍全量
FR-LR-12  已连接列表设检视走 _commit_mobile_target（含确认）
FR-LR-13  镜像入口 tag=镜像，确认文案含「镜像」
FR-LR-14  源码静态：启动 / 提交入口不得绕过确认
FR-LR-15  _devices 与 list_local_devices 合并后才能判多机
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import cast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QWidget  # noqa: E402

from autopilot.mgmt.local_devices import LocalDevice  # noqa: E402
from autopilot.mgmt.local_runner_guard import (  # noqa: E402
    ACTION_CANCEL,
    ACTION_EXCLUDE,
    ACTION_REPORT_ALL,
    SCENARIO_START_MULTI,
    SCENARIO_START_SINGLE,
)
from autopilot.ui.main_window.mgmt_runner_web import MgmtRunnerWebMixin  # noqa: E402


REQUIREMENT_MATRIX: tuple[tuple[str, str, str], ...] = (
    ("FR-LR-01", "TC-01", "test_chain_start_runner_without_inspect_does_not_prompt"),
    ("FR-LR-02", "TC-02", "test_chain_start_runner_multi_exclude_then_heartbeat"),
    ("FR-LR-03", "TC-03", "test_chain_start_runner_single_allows_without_exclude"),
    ("FR-LR-04", "TC-04", "test_chain_start_runner_cancel_does_not_start"),
    ("FR-LR-05", "TC-05", "test_chain_commit_inspect_excludes_when_reported"),
    ("FR-LR-06", "TC-06", "test_chain_commit_skips_prompt_when_already_excluded"),
    ("FR-LR-07", "TC-07", "test_chain_commit_keep_reporting"),
    ("FR-LR-08", "TC-08", "test_chain_commit_cancel_restores_bound_udid"),
    ("FR-LR-09", "TC-09", "test_chain_web_inspect_skips_runner_prompt"),
    ("FR-LR-10", "TC-10", "test_chain_cancel_inspect_releases_exclude"),
    ("FR-LR-10", "TC-11", "test_chain_device_gone_releases_exclude"),
    ("FR-LR-11", "TC-02", "test_chain_start_runner_multi_exclude_then_heartbeat"),
    ("FR-LR-12", "TC-12", "test_chain_set_inspect_from_list_goes_through_commit"),
    ("FR-LR-13", "TC-13", "test_chain_mirror_commit_uses_mirror_copy"),
    ("FR-LR-14", "TC-14", "test_chain_static_entries_call_confirm"),
    ("FR-LR-15", "TC-15", "test_chain_start_runner_merges_devices_and_probe"),
)


@pytest.fixture()
def qt_app():
    from tests._qt import get_qt_app

    return get_qt_app()


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    (tmp_path / "cfg").mkdir()
    from autopilot.runtime import settings

    yield settings


class _Proc:
    def __init__(self):
        self.started = []
        self.running = False
        self.runner_id = ""

    def start(self, server, token, *, runner_id=None, poll_interval=3.0):
        _ = poll_interval
        rid = runner_id or ""
        self.started.append((server, token, rid))
        self.running = True
        self.runner_id = rid
        return rid


class _RunnerHost(MgmtRunnerWebMixin, QWidget):
    def __init__(self):
        QWidget.__init__(self)
        self.console = SimpleNamespace(log=lambda *_a, **_k: None)
        self._local_runner = _Proc()
        self.refresh = 0
        self._inspect_platform = ""
        self._inspect_udid = ""
        self._inspect_chosen = False
        self._inspect_ctx = None
        self._devices = ([], [])
        self.mirror = SimpleNamespace(active=lambda: False)

    @staticmethod
    def _mgmt_is_platform_admin() -> bool:
        from autopilot.ui.mgmt_role import is_platform_admin_role

        return is_platform_admin_role()

    def _mgmt_refresh_session_ui(self) -> None:
        self.refresh += 1

    def _mgmt_local_runner(self):
        return self._local_runner


def _admin_start_env(monkeypatch, isolated_settings, runner_id="ide-guard-1"):
    class _FakeClient:
        @staticmethod
        def register_runner(payload):
            return payload

        @staticmethod
        def issue_scoped_runner_token(*_a, **_k):
            return {"api_token": "scoped-org-token"}

        def close(self):
            pass

    monkeypatch.setattr(
        "autopilot.mgmt.ensure_user_session",
        lambda **_k: (_FakeClient(), "jwt"),
    )
    monkeypatch.setattr(isolated_settings, "mc_server_url", lambda: "http://127.0.0.1:8000")
    monkeypatch.setattr(isolated_settings, "mc_project_id", lambda: "")
    monkeypatch.setattr(isolated_settings, "mc_org_id", lambda: "org-scope")
    monkeypatch.setattr(isolated_settings, "mc_user_role", lambda: "admin")
    monkeypatch.setattr(isolated_settings, "mc_api_token", lambda: "")
    monkeypatch.setattr(
        "autopilot.mgmt.local_runner.default_local_runner_id",
        lambda: runner_id,
    )


def _inspect_host(
    *,
    runner_id="ide-in-1",
    running=True,
    plat="Android",
    udid="AND-1",
    android=None,
    ios=None,
):
    from autopilot.ui.widgets.console import Console
    from autopilot.ui.widgets.inspector_panel import InspectorPanel
    from autopilot.ui.widgets.mirror_panel import MirrorPanel
    from autopilot.ui.main_window.device import DeviceMixin
    from autopilot.ui.main_window.device_readiness import DeviceLists

    android = ["AND-1"] if android is None else list(android)
    ios = [] if ios is None else list(ios)

    class _InspectHost(DeviceMixin, QWidget):
        def __init__(self):
            QWidget.__init__(self)
            self.console = cast(Console, SimpleNamespace(log=lambda *_a, **_k: None))
            self._inspect_ctx = None
            self._inspect_platform = plat
            self._inspect_udid = udid
            self._inspect_chosen = False
            self._devices = (android, ios)
            self._local_runner = SimpleNamespace(running=running, runner_id=runner_id)
            self.mirror = cast(
                MirrorPanel,
                SimpleNamespace(
                    active=lambda: False,
                    view=SimpleNamespace(set_hint=lambda *_a, **_k: None),
                    set_mobile_available=lambda *_a, **_k: None,
                    platform_name=lambda: "",
                ),
            )
            self.inspector = cast(
                InspectorPanel,
                SimpleNamespace(
                    view=SimpleNamespace(set_hint=lambda *_a, **_k: None),
                    sync_cancel_btn=lambda: None,
                    refresh=lambda: None,
                ),
            )

        def _device_lists(self):
            a, i = getattr(self, "_devices", (android, ios))
            return DeviceLists.from_lists(list(a or []), list(i or []))

        def _update_device_status(self):
            return None

        def _warn_inspect_unavailable(self, message: str) -> None:
            return None

        def _sync_device_panel_controls(self):
            return None

        def _watch_device_gone(self, *_a, **_k):
            return None

        def _dep_hint(self, _plat):
            return ""

        def _close_mobile_driver(self, _ctx):
            return None

        def _quit_web_driver(self, _ctx):
            return None

        def _stop_our_appium(self):
            return None

    return _InspectHost()


def test_requirement_matrix_covers_all_fr():
    fr_ids = {row[0] for row in REQUIREMENT_MATRIX}
    expected = {f"FR-LR-{i:02d}" for i in range(1, 16)}
    assert fr_ids == expected


def test_chain_start_runner_without_inspect_does_not_prompt(
    qt_app, isolated_settings, monkeypatch
):
    asked = {"n": 0}

    def _boom(*_a, **_k):
        asked["n"] += 1
        return ACTION_CANCEL

    monkeypatch.setattr("autopilot.ui.confirm.ask_local_runner_prompt", _boom)
    monkeypatch.setattr("autopilot.mgmt.local_devices.list_local_devices", lambda: [])
    _admin_start_env(monkeypatch, isolated_settings)
    h = _RunnerHost()
    h.mgmt_start_local_runner()
    assert asked["n"] == 0
    assert h._local_runner.started


def test_chain_start_runner_multi_exclude_then_heartbeat(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    """TC-02 / FR-LR-02+11：启动摘除 → 落盘 → 心跳 devices 不含检视机。"""
    from autopilot.runner.agent import RunnerAgent
    from autopilot.runner.contract import DeviceInfo
    from autopilot.runner.device_policy import load_device_policy

    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    asked = []

    def _ask(_parent, prompt):
        asked.append(prompt)
        return ACTION_EXCLUDE

    monkeypatch.setattr("autopilot.ui.confirm.ask_local_runner_prompt", _ask)
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_local_devices",
        lambda: [
            LocalDevice(udid="PHONE-1", platform="ios"),
            LocalDevice(udid="PHONE-2", platform="android"),
        ],
    )
    _admin_start_env(monkeypatch, isolated_settings, runner_id="ide-ex-1")
    h = _RunnerHost()
    h._inspect_platform = "iOS"
    h._inspect_udid = "PHONE-1"
    h._inspect_chosen = True
    h.mgmt_start_local_runner()
    assert asked and asked[0].scenario == SCENARIO_START_MULTI
    assert asked[0].yes_text == "启动并摘除该机"
    assert h._local_runner.started == [
        ("http://127.0.0.1:8000", "scoped-org-token", "ide-ex-1")
    ]
    assert load_device_policy("ide-ex-1").exclude_udids == {"PHONE-1"}

    inventory = [
        DeviceInfo(udid="PHONE-1", platform="ios"),
        DeviceInfo(udid="PHONE-2", platform="android"),
    ]
    monkeypatch.setattr(
        "autopilot.runner.agent.list_local_devices", lambda: list(inventory)
    )
    monkeypatch.setattr(
        "autopilot.runner.agent.probe_host_capabilities", lambda: ([], [])
    )

    from autopilot.runner.client import PlatformClient

    class _Client:
        def __init__(self):
            self.bodies = []

        def heartbeat(self, body):
            self.bodies.append(body)
            return {"device_policy_revision": 0}

    agent = RunnerAgent("http://platform", runner_id="ide-ex-1")
    client = cast(PlatformClient, _Client())
    agent._heartbeat_once(client)
    assert [d.udid for d in client.bodies[0].inventory] == ["PHONE-1", "PHONE-2"]
    assert [d.udid for d in client.bodies[0].devices] == ["PHONE-2"]


def test_chain_start_runner_single_allows_without_exclude(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    asked = []

    def _ask(_parent, prompt):
        asked.append(prompt)
        return ACTION_REPORT_ALL

    monkeypatch.setattr("autopilot.ui.confirm.ask_local_runner_prompt", _ask)
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_local_devices",
        lambda: [LocalDevice(udid="ONLY-1", platform="android")],
    )
    _admin_start_env(monkeypatch, isolated_settings, runner_id="ide-single-1")
    h = _RunnerHost()
    h._inspect_platform = "Android"
    h._inspect_udid = "ONLY-1"
    h._inspect_chosen = True
    h.mgmt_start_local_runner()
    assert asked and asked[0].scenario == SCENARIO_START_SINGLE
    assert asked[0].yes_text == "仍然启动"
    assert h._local_runner.started
    from autopilot.runner.device_policy import load_device_policy

    assert load_device_policy("ide-single-1").exclude_udids == set()


def test_chain_start_runner_cancel_does_not_start(
    qt_app, isolated_settings, monkeypatch
):
    monkeypatch.setattr(
        "autopilot.ui.confirm.ask_local_runner_prompt",
        lambda *_a, **_k: ACTION_CANCEL,
    )
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_local_devices",
        lambda: [LocalDevice(udid="ONLY-1", platform="android")],
    )
    _admin_start_env(monkeypatch, isolated_settings)
    h = _RunnerHost()
    h._inspect_platform = "Android"
    h._inspect_udid = "ONLY-1"
    h._inspect_ctx = object()
    h.mgmt_start_local_runner()
    assert h._local_runner.started == []


def test_chain_commit_inspect_excludes_when_reported(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    asked = []

    def _ask(_parent, prompt):
        asked.append(prompt)
        return ACTION_EXCLUDE

    monkeypatch.setattr("autopilot.ui.main_window.device.ask_local_runner_prompt", _ask)
    h = _inspect_host(runner_id="ide-in-1")
    assert h._commit_mobile_target(tag="检视") is True
    assert asked and asked[0].yes_text == "继续并摘除上报"
    assert h._inspect_chosen is True
    from autopilot.runner.device_policy import load_device_policy

    assert load_device_policy("ide-in-1").exclude_udids == {"AND-1"}


def test_chain_commit_skips_prompt_when_already_excluded(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    from autopilot.runner.device_policy import add_exclude_udids

    add_exclude_udids("ide-in-2", {"AND-1"})
    asked = {"n": 0}
    monkeypatch.setattr(
        "autopilot.ui.main_window.device.ask_local_runner_prompt",
        lambda *_a, **_k: asked.__setitem__("n", asked["n"] + 1) or ACTION_CANCEL,
    )
    h = _inspect_host(runner_id="ide-in-2")
    assert h._commit_mobile_target(tag="镜像") is True
    assert asked["n"] == 0
    assert h._inspect_chosen is True


def test_chain_commit_keep_reporting(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    monkeypatch.setattr(
        "autopilot.ui.main_window.device.ask_local_runner_prompt",
        lambda *_a, **_k: ACTION_REPORT_ALL,
    )
    h = _inspect_host(runner_id="ide-in-3")
    assert h._commit_mobile_target(tag="检视") is True
    from autopilot.runner.device_policy import load_device_policy

    assert h._inspect_chosen is True
    assert load_device_policy("ide-in-3").exclude_udids == set()


def test_chain_commit_cancel_restores_bound_udid(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    monkeypatch.setattr(
        "autopilot.ui.main_window.device.ask_local_runner_prompt",
        lambda *_a, **_k: ACTION_CANCEL,
    )
    h = _inspect_host(
        runner_id="ide-in-4",
        udid="AND-2",
        android=["AND-1", "AND-2"],
    )
    h._runner_guard_bound_plat = "Android"
    h._runner_guard_bound_udid = "AND-1"
    h._inspect_chosen = True
    assert h._commit_mobile_target(tag="检视") is False
    assert h._inspect_udid == "AND-1"
    assert h._inspect_platform == "Android"
    from autopilot.runner.device_policy import load_device_policy

    assert load_device_policy("ide-in-4").exclude_udids == set()


def test_chain_web_inspect_skips_runner_prompt(
    qt_app, isolated_settings, monkeypatch
):
    asked = {"n": 0}
    monkeypatch.setattr(
        "autopilot.ui.main_window.device.ask_local_runner_prompt",
        lambda *_a, **_k: asked.__setitem__("n", asked["n"] + 1) or ACTION_CANCEL,
    )
    h = _inspect_host(plat="Web", udid="")
    h._inspect_url = "https://example.test"
    assert h._confirm_inspect_with_local_runner("检视") is True
    assert asked["n"] == 0


def test_chain_cancel_inspect_releases_exclude(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    from autopilot.runner.device_policy import add_exclude_udids, load_device_policy

    add_exclude_udids("ide-in-5", {"AND-1"})
    h = _inspect_host(runner_id="ide-in-5")
    h._inspect_chosen = True
    h._on_inspect_cancelled()
    assert h._inspect_chosen is False
    assert load_device_policy("ide-in-5").exclude_udids == set()


def test_chain_device_gone_releases_exclude(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    from autopilot.runner.device_policy import add_exclude_udids, load_device_policy

    add_exclude_udids("ide-in-6", {"AND-1"})
    h = _inspect_host(runner_id="ide-in-6")
    h._inspect_chosen = True
    h._on_devices_changed([], [])
    assert h._inspect_chosen is False
    assert load_device_policy("ide-in-6").exclude_udids == set()


def test_chain_set_inspect_from_list_goes_through_commit(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    from autopilot.ui.device_list_menu import ConnectedDevice
    from autopilot.runner.device_policy import load_device_policy

    asked = []

    def _ask(_parent, prompt):
        asked.append(prompt)
        return ACTION_EXCLUDE

    monkeypatch.setattr("autopilot.ui.main_window.device.ask_local_runner_prompt", _ask)
    h = _inspect_host(runner_id="ide-in-7", udid="", android=["devA", "devB"])
    h._set_inspect_from_connected(ConnectedDevice("Android", "devB"))
    assert asked and "检视" in asked[0].text
    assert h._inspect_chosen is True
    assert h._inspect_udid == "devB"
    assert load_device_policy("ide-in-7").exclude_udids == {"devB"}


def test_chain_mirror_commit_uses_mirror_copy(
    qt_app, isolated_settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner"))
    asked = []

    def _ask(_parent, prompt):
        asked.append(prompt)
        return ACTION_EXCLUDE

    monkeypatch.setattr("autopilot.ui.main_window.device.ask_local_runner_prompt", _ask)
    h = _inspect_host(runner_id="ide-in-8")
    assert h._commit_mobile_target(tag="镜像") is True
    assert asked and asked[0].title == "镜像与本机 Runner"
    assert "镜像" in asked[0].text


def test_chain_static_entries_call_confirm():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runner_web = os.path.join(
        root, "autopilot", "ui", "main_window", "mgmt_runner_web.py"
    )
    device_py = os.path.join(root, "autopilot", "ui", "main_window", "device.py")
    start = open(runner_web, encoding="utf-8").read()
    device = open(device_py, encoding="utf-8").read()
    start_fn = start[start.find("def mgmt_start_local_runner") :]
    start_fn = start_fn[: start_fn.find("\n    def ")]
    commit_fn = device[device.find("def _commit_mobile_target") :]
    commit_fn = commit_fn[: commit_fn.find("\n    def _confirm_inspect")]
    set_fn = device[device.find("def _set_inspect_from_connected") :]
    set_fn = set_fn[: set_fn.find("\n    def _show_info_for_connected")]
    assert "_mgmt_confirm_local_runner_vs_inspect" in start_fn
    assert "_confirm_inspect_with_local_runner" in commit_fn
    assert "_commit_mobile_target" in set_fn


def test_chain_start_runner_merges_devices_and_probe(
    qt_app, isolated_settings, monkeypatch
):
    """TC-15 / FR-LR-15：UI 列表只有另一台、探测只有检视机 → 仍判多机。"""
    asked = []

    def _ask(_parent, prompt):
        asked.append(prompt)
        return ACTION_CANCEL

    monkeypatch.setattr("autopilot.ui.confirm.ask_local_runner_prompt", _ask)
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_local_devices",
        lambda: [LocalDevice(udid="PHONE-1", platform="ios")],
    )
    _admin_start_env(monkeypatch, isolated_settings)
    h = _RunnerHost()
    h._devices = (["PHONE-2"], [])
    h._inspect_platform = "iOS"
    h._inspect_udid = "PHONE-1"
    h._inspect_chosen = True
    h.mgmt_start_local_runner()
    assert asked and asked[0].scenario == SCENARIO_START_MULTI
    assert h._local_runner.started == []


def test_ask_local_runner_prompt_maps_tri_buttons(qt_app, monkeypatch):
    from autopilot.mgmt.local_runner_guard import start_runner_prompt
    from autopilot.ui.confirm import ask_local_runner_prompt

    prompt = start_runner_prompt(
        inspect_udid="A",
        inspect_kind_label="检视",
        local_udids=["A", "B"],
    )
    monkeypatch.setattr(
        "autopilot.ui.confirm.confirm_tri",
        lambda *_a, **_k: "yes",
    )
    assert ask_local_runner_prompt(None, prompt) == ACTION_EXCLUDE
    monkeypatch.setattr(
        "autopilot.ui.confirm.confirm_tri",
        lambda *_a, **_k: "no",
    )
    assert ask_local_runner_prompt(None, prompt) == ACTION_REPORT_ALL
    monkeypatch.setattr(
        "autopilot.ui.confirm.confirm_tri",
        lambda *_a, **_k: "cancel",
    )
    assert ask_local_runner_prompt(None, prompt) == ACTION_CANCEL
