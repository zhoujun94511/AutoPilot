"""设备级隔离：独立 Appium 端口、粘滞 UDID、appium_stop 不再跳过。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from subprocess import Popen
from typing import cast

import pytest

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.mobile.appium_server import (
    AppiumServer,
    reset_appium_server_pool_for_tests,
    stop_local_appium,
)
from autopilot.keywords.mobile.session import appium_start, appium_stop
from autopilot.runner.job_slots import JobSlotTracker
from autopilot.runtime.device_pool import build_sessions
from autopilot.runtime.device_runtime import (
    acquire_device_runtime,
    peek_device_runtime,
    release_device_runtime,
    reset_device_runtimes_for_tests,
    runtimes_for_vars,
)
from autopilot.runtime.device_session import DeviceSession


def test_android_slots_get_distinct_appium_and_uia2_ports():
    a = DeviceSession.from_slot("android", "A", slot=0)
    b = DeviceSession.from_slot("android", "B", slot=1)
    va, vb = a.to_ctx_vars(), b.to_ctx_vars()
    assert va["__appium_server__"] == "http://127.0.0.1:4723"
    assert vb["__appium_server__"] == "http://127.0.0.1:4724"
    assert va["__appium_caps__"]["appium:systemPort"] == 8200
    assert vb["__appium_caps__"]["appium:systemPort"] == 8201
    assert va["__appium_caps__"]["appium:chromedriverPort"] != vb["__appium_caps__"]["appium:chromedriverPort"]


def test_udid_port_assignment_is_sticky():
    reset_device_runtimes_for_tests()
    first = acquire_device_runtime("PHONE-A", "android")
    release_device_runtime("PHONE-A")
    second = acquire_device_runtime("PHONE-B", "android")
    again = acquire_device_runtime("PHONE-A", "android")
    assert first.slot != second.slot
    assert again.slot == first.slot
    assert again.ports.appium_port == first.ports.appium_port
    release_device_runtime("PHONE-A")
    release_device_runtime("PHONE-B")


def test_build_sessions_uses_sticky_udid_not_list_index():
    reset_device_runtimes_for_tests()
    first = build_sessions("android", ["X", "Y"], workers=2)
    for s in first:
        release_device_runtime(s.udid)
    shuffled = build_sessions("android", ["Y", "X"], workers=2)
    by_udid = {s.udid: s.appium_url for s in shuffled}
    assert by_udid["X"] == first[0].appium_url
    assert by_udid["Y"] == first[1].appium_url
    for s in shuffled:
        release_device_runtime(s.udid)


def test_appium_stop_runs_in_parallel_and_only_hits_this_manager():
    ctx = ExecutionContext()
    ctx.set_var("__parallel_device_udids__", ["U1", "U2"])
    ctx.set_var("__appium_server__", "http://127.0.0.1:4724")
    mgr = MagicMock()
    with patch("autopilot.keywords.mobile.session.get_manager", return_value=mgr):
        appium_stop(ctx)
    assert mgr.stop_server.call_count == 1


def test_stop_local_appium_does_not_kill_other_ports():
    reset_appium_server_pool_for_tests()
    a = AppiumServer(host="127.0.0.1", port=47291)
    b = AppiumServer(host="127.0.0.1", port=47292)
    a._proc = cast(Popen | None, object())  # noqa: SLF001
    b._proc = cast(Popen | None, object())  # noqa: SLF001
    stopped: list[int] = []

    def _stop_a() -> None:
        stopped.append(a.port)
        a._proc = None  # noqa: SLF001

    def _stop_b() -> None:
        stopped.append(b.port)
        b._proc = None  # noqa: SLF001

    a.stop = _stop_a  # type: ignore[method-assign]
    b.stop = _stop_b  # type: ignore[method-assign]
    from autopilot.keywords.mobile import appium_server as mod

    mod._SERVER_POOL[("127.0.0.1", 47291)] = a
    mod._SERVER_POOL[("127.0.0.1", 47292)] = b
    stop_local_appium("127.0.0.1", 47291)
    assert stopped == [47291]
    assert b._proc is not None  # noqa: SLF001
    reset_appium_server_pool_for_tests()


def test_suite_teardown_stops_only_leased_device_ports(monkeypatch):
    from autopilot.engine import suite as suite_mod

    reset_device_runtimes_for_tests()
    acquire_device_runtime("D1", "android")
    acquire_device_runtime("D2", "android")
    seen: list[int] = []

    def _stop(host, port):  # noqa: ARG001
        seen.append(int(port))

    monkeypatch.delenv("AUTOPILOT_RUNNER_KEEP_APPIUM", raising=False)
    monkeypatch.setattr(
        "autopilot.keywords.mobile.appium_server.stop_local_appium", _stop
    )
    suite_mod._teardown_suite_appium(
        {"__parallel_device_udids__": ["D1", "D2"]}
    )
    assert sorted(seen) == [4723, 4724]
    release_device_runtime("D1")
    release_device_runtime("D2")


def test_job_slots_allow_disjoint_devices_and_block_overlap():
    t = JobSlotTracker()
    assert t.try_reserve("j1", ["a1"]) == ""
    assert t.try_reserve("j2", ["i1"]) == ""
    assert "devices busy" in t.try_reserve("j3", ["a1"])
    t.release("j1")
    assert t.try_reserve("j3", ["a1"]) == ""
    t.release("j2")
    t.release("j3")


def test_job_slots_serialize_host_exclusive_jobs():
    t = JobSlotTracker()
    assert t.try_reserve("web1", []) == ""
    assert "host-exclusive" in t.try_reserve("web2", [])
    assert t.try_reserve("android1", ["u1"]) == ""
    t.release("web1")
    assert t.try_reserve("web2", []) == ""


def test_job_slots_release_one_side_does_not_drop_the_other():
    """结束 web 不释放设备槽；结束设备不释放 web 槽。"""
    t = JobSlotTracker()
    assert t.try_reserve("web1", []) == ""
    assert t.try_reserve("and1", ["a1"]) == ""
    t.release("and1")
    assert t.has_web()
    assert t.try_reserve("and2", ["a1"]) == ""
    t.release("web1")
    assert t.busy_udids() == {"a1"}
    assert t.try_reserve("web2", []) == ""
    t.release("and2")
    t.release("web2")


def test_runtimes_for_vars_reads_single_and_parallel_udids():
    reset_device_runtimes_for_tests()
    acquire_device_runtime("S1", "android")
    acquire_device_runtime("P1", "android")
    acquire_device_runtime("P2", "ios")
    one = runtimes_for_vars({"__device_udid__": "S1"})
    assert [r.udid for r in one] == ["S1"]
    many = runtimes_for_vars({"__parallel_device_udids__": ["P2", "P1"]})
    assert [r.udid for r in many] == ["P2", "P1"]
    own = runtimes_for_vars({
        "__parallel_device_udids__": ["P2", "P1"],
        "__device_udid__": "P1",
    })
    assert [r.udid for r in own] == ["P1"]
    release_device_runtime("S1")
    release_device_runtime("P1")
    release_device_runtime("P2")


def test_slot_recycle_when_max_slots_exhausted(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_MAX_DEVICE_SLOTS", "2")
    reset_device_runtimes_for_tests()
    a = acquire_device_runtime("A", "android")
    b = acquire_device_runtime("B", "android")
    release_device_runtime("A")
    c = acquire_device_runtime("C", "android")
    assert peek_device_runtime("A") is None
    assert c.slot == a.slot
    assert c.ports.appium_port == a.ports.appium_port
    assert b.slot != c.slot
    release_device_runtime("B")
    release_device_runtime("C")


def test_slot_recycle_stops_old_appium_port(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_MAX_DEVICE_SLOTS", "2")
    reset_device_runtimes_for_tests()
    a = acquire_device_runtime("A", "android")
    acquire_device_runtime("B", "android")
    release_device_runtime("A")
    seen: list[int] = []
    monkeypatch.setattr(
        "autopilot.keywords.mobile.appium_server.stop_local_appium",
        lambda host, port: seen.append(int(port)),
    )
    acquire_device_runtime("C", "android")
    assert seen == [a.ports.appium_port]
    release_device_runtime("B")
    release_device_runtime("C")


def test_slot_exhausted_while_all_leased_raises(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_MAX_DEVICE_SLOTS", "2")
    reset_device_runtimes_for_tests()
    acquire_device_runtime("A", "android")
    acquire_device_runtime("B", "android")
    try:
        with pytest.raises(RuntimeError, match="设备隔离槽位已满"):
            acquire_device_runtime("C", "android")
    finally:
        release_device_runtime("A")
        release_device_runtime("B")


def test_keep_appium_skips_per_device_port_stop(monkeypatch):
    from autopilot.engine import suite as suite_mod

    reset_device_runtimes_for_tests()
    acquire_device_runtime("KEEP1", "android")
    seen: list[int] = []
    monkeypatch.setenv("AUTOPILOT_RUNNER_KEEP_APPIUM", "1")
    monkeypatch.setattr(
        "autopilot.keywords.mobile.appium_server.stop_local_appium",
        lambda host, port: seen.append(int(port)),
    )
    suite_mod._teardown_suite_appium({"__device_udid__": "KEEP1"})
    assert seen == []
    release_device_runtime("KEEP1")


def test_teardown_worker_vars_only_stop_own_port(monkeypatch):
    from autopilot.engine import suite as suite_mod

    reset_device_runtimes_for_tests()
    acquire_device_runtime("D1", "android")
    acquire_device_runtime("D2", "android")
    seen: list[int] = []
    monkeypatch.delenv("AUTOPILOT_RUNNER_KEEP_APPIUM", raising=False)
    monkeypatch.setattr(
        "autopilot.keywords.mobile.appium_server.stop_local_appium",
        lambda host, port: seen.append(int(port)),
    )
    suite_mod._teardown_suite_appium({
        "__parallel_device_udids__": ["D1", "D2"],
        "__device_udid__": "D1",
        "__appium_server__": "http://127.0.0.1:4723",
    })
    assert seen == [4723]
    release_device_runtime("D1")
    release_device_runtime("D2")


def test_teardown_falls_back_to_appium_server_url(monkeypatch):
    from autopilot.engine import suite as suite_mod

    reset_device_runtimes_for_tests()
    seen: list[tuple[str, int]] = []
    monkeypatch.delenv("AUTOPILOT_RUNNER_KEEP_APPIUM", raising=False)
    monkeypatch.setattr(
        "autopilot.keywords.mobile.appium_server.stop_local_appium",
        lambda host, port: seen.append((str(host), int(port))),
    )
    suite_mod._teardown_suite_appium(
        {"__appium_server__": "http://127.0.0.1:4728"}
    )
    assert seen == [("127.0.0.1", 4728)]


def test_appium_start_binds_isolated_server_and_caps():
    ctx = ExecutionContext()
    ctx.set_var("__current_platform__", "android")
    ctx.set_var("__appium_server__", "http://127.0.0.1:4725")
    ctx.set_var("__appium_caps__", {"appium:systemPort": 8202})
    mgr = MagicMock()
    mgr.platform = "android"
    mgr.backend_mode = "auto"
    mgr.extra_caps = {}
    mgr.server = "http://127.0.0.1:4723"
    with patch("autopilot.keywords.mobile.session.get_manager", return_value=mgr):
        appium_start(ctx)
    assert mgr.server == "http://127.0.0.1:4725"
    assert mgr.extra_caps["appium:systemPort"] == 8202
    mgr.start_server.assert_called_once()


def test_localhost_shares_pool_with_loopback(monkeypatch):
    from autopilot.keywords.mobile.appium_server import (
        _norm_host,
        acquire_local_appium,
        reset_appium_server_pool_for_tests,
    )

    assert _norm_host("localhost") == "127.0.0.1"
    assert _norm_host("::1") == "127.0.0.1"
    reset_appium_server_pool_for_tests()
    monkeypatch.setattr(AppiumServer, "ensure_running", lambda self, timeout=None: None)
    a = acquire_local_appium("127.0.0.1", 47311)
    b = acquire_local_appium("localhost", 47311)
    assert a is b
    reset_appium_server_pool_for_tests()


def test_stop_started_servers_can_target_one_port():
    from autopilot.keywords.mobile import appium_server as mod

    reset_appium_server_pool_for_tests()
    a = AppiumServer(host="127.0.0.1", port=47321)
    b = AppiumServer(host="127.0.0.1", port=47322)
    stopped: list[int] = []

    def _bind(srv: AppiumServer):
        def _stop() -> None:
            stopped.append(srv.port)
            srv._proc = None  # noqa: SLF001

        srv.stop = _stop  # type: ignore[method-assign]
        srv._proc = object()  # noqa: SLF001
        mod._SERVER_POOL[("127.0.0.1", srv.port)] = srv

    _bind(a)
    _bind(b)
    mod.stop_started_appium_servers(ports=[47321])
    assert stopped == [47321]
    assert ("127.0.0.1", 47322) in mod._SERVER_POOL
    reset_appium_server_pool_for_tests()


def test_stop_local_appium_drops_pool_entry_via_started_by_us():
    from autopilot.keywords.mobile import appium_server as mod

    reset_appium_server_pool_for_tests()
    srv = AppiumServer(host="127.0.0.1", port=47331)
    srv._proc = object()  # noqa: SLF001
    assert srv.started_by_us() is True

    def _stop() -> None:
        srv._proc = None  # noqa: SLF001

    srv.stop = _stop  # type: ignore[method-assign]
    mod._SERVER_POOL[("127.0.0.1", 47331)] = srv
    stop_local_appium("127.0.0.1", 47331)
    assert srv.started_by_us() is False
    assert ("127.0.0.1", 47331) not in mod._SERVER_POOL
    reset_appium_server_pool_for_tests()
