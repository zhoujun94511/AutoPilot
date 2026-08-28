"""run_suite 设备隔离注入与失败时释放槽位（白盒）。"""

from __future__ import annotations

import pytest

from autopilot.engine.suite import SuiteResult
from autopilot.model.testcase import TestCase
import autopilot.runtime.device_runtime as device_runtime_mod
from autopilot.runtime.device_runtime import (
    peek_device_runtime,
    reset_device_runtimes_for_tests,
)


def _refs(udid: str) -> int:
    registry = getattr(device_runtime_mod, "_REGISTRY")
    refs = getattr(registry, "_refs")
    return int(refs.get(udid) or 0)


def test_run_suite_sequential_injects_android_isolation(monkeypatch):
    from autopilot.engine import run as run_mod

    captured: dict = {}

    def fake_get(_mode):
        def _run(_cases, cfg):
            captured["vars"] = dict(cfg.base_vars)
            return SuiteResult(name=cfg.name)

        return _run

    monkeypatch.setattr(run_mod, "get", fake_get)
    reset_device_runtimes_for_tests()
    result = run_mod.run_suite(
        [TestCase(name="t")],
        mode="sequential",
        platform="android",
        device_udids=["UDID-SEQ"],
    )
    assert isinstance(result, SuiteResult)
    v = captured["vars"]
    assert v["__device_udid__"] == "UDID-SEQ"
    assert v["__appium_server__"] == "http://127.0.0.1:4723"
    assert v["__appium_caps__"]["appium:systemPort"] == 8200
    assert v["__appium_caps__"]["appium:chromedriverPort"] == 9515
    assert v["__appium_caps__"]["appium:mjpegServerPort"] == 7810
    assert _refs("UDID-SEQ") == 0
    assert peek_device_runtime("UDID-SEQ") is not None


def test_run_suite_parallel_injects_distinct_servers(monkeypatch):
    from autopilot.engine import run as run_mod

    captured: dict = {}

    def fake_get(_mode):
        def _run(_cases, cfg):
            captured["sessions"] = list(cfg.device_sessions)
            captured["vars"] = dict(cfg.base_vars)
            return SuiteResult(name=cfg.name)

        return _run

    monkeypatch.setattr(run_mod, "get", fake_get)
    reset_device_runtimes_for_tests()
    run_mod.run_suite(
        [TestCase(name="t")],
        mode="parallel_device",
        platform="android",
        device_udids=["PAR-A", "PAR-B"],
        parallel_workers=2,
    )
    sessions = captured["sessions"]
    assert len(sessions) == 2
    urls = {s.udid: s.appium_url for s in sessions}
    assert urls["PAR-A"] != urls["PAR-B"]
    assert captured["vars"]["__parallel_device_udids__"] == ["PAR-A", "PAR-B"]
    assert "__device_udid__" not in captured["vars"]
    assert _refs("PAR-A") == 0
    assert _refs("PAR-B") == 0


def test_run_suite_releases_lease_when_strategy_raises(monkeypatch):
    from autopilot.engine import run as run_mod

    def fake_get(_mode):
        def _boom(_cases, _cfg):
            raise RuntimeError("exec fail")

        return _boom

    monkeypatch.setattr(run_mod, "get", fake_get)
    reset_device_runtimes_for_tests()
    with pytest.raises(RuntimeError, match="exec fail"):
        run_mod.run_suite(
            [TestCase(name="t")],
            mode="sequential",
            platform="android",
            device_udids=["UDID-FAIL"],
        )
    assert _refs("UDID-FAIL") == 0
    assert peek_device_runtime("UDID-FAIL") is not None


def test_run_suite_sequential_injects_ios_wda_ports(monkeypatch):
    from autopilot.engine import run as run_mod

    captured: dict = {}

    def fake_get(_mode):
        def _run(_cases, cfg):
            captured["vars"] = dict(cfg.base_vars)
            return SuiteResult(name=cfg.name)

        return _run

    monkeypatch.setattr(run_mod, "get", fake_get)
    reset_device_runtimes_for_tests()
    run_mod.run_suite(
        [TestCase(name="t")],
        mode="sequential",
        platform="ios",
        device_udids=["IOS-SEQ"],
        backend_mode="appium",
    )
    v = captured["vars"]
    assert v["__device_udid__"] == "IOS-SEQ"
    assert v["__appium_server__"] == "http://127.0.0.1:4723"
    assert v["__wda_local_port__"] == 8100
    assert v["__tunnel_info_port__"] == 28100
    assert v["__mjpeg_local_port__"] == 9100
    assert _refs("IOS-SEQ") == 0


def test_device_runtime_lease_releases_on_success_and_error():
    from autopilot.runtime.device_runtime import DeviceRuntimeLease, acquire_device_runtime

    reset_device_runtimes_for_tests()
    acquire_device_runtime("LEASE-OK", "android")
    with DeviceRuntimeLease() as lease:
        lease.hold(["LEASE-OK"])
        assert _refs("LEASE-OK") == 1
    assert _refs("LEASE-OK") == 0

    acquire_device_runtime("LEASE-ERR", "android")
    with pytest.raises(RuntimeError, match="boom"):
        with DeviceRuntimeLease() as lease:
            lease.hold(["LEASE-ERR"])
            raise RuntimeError("boom")
    assert _refs("LEASE-ERR") == 0


def test_build_sessions_releases_partial_acquire_via_lease(monkeypatch):
    from autopilot.runtime.device_pool import build_sessions
    from autopilot.runtime.device_runtime import DeviceRuntimeLease
    from autopilot.runtime.device_session import DeviceSession

    reset_device_runtimes_for_tests()
    real = DeviceSession.for_device
    n = {"i": 0}

    def flaky(plat, udid, **kw):
        n["i"] += 1
        if n["i"] >= 3:
            raise RuntimeError("slot full")
        return real(plat, udid, **kw)

    monkeypatch.setattr(
        "autopilot.runtime.device_pool.DeviceSession.for_device", flaky
    )
    with pytest.raises(RuntimeError, match="slot full"):
        with DeviceRuntimeLease() as lease:
            build_sessions("android", ["A", "B", "C"], workers=3, lease=lease)
    assert _refs("A") == 0
    assert _refs("B") == 0


def test_job_log_handler_drops_other_job_records():
    import logging

    from autopilot.runtime.job_log import JOB_LOG_ID
    from autopilot.runner.execute import _ListHandler

    handler = _ListHandler("job-a")
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "hello", (), None
    )
    token = JOB_LOG_ID.set("job-b")
    try:
        handler.emit(record)
        assert handler.lines == []
    finally:
        JOB_LOG_ID.reset(token)
    token = JOB_LOG_ID.set("job-a")
    try:
        handler.emit(record)
        assert handler.lines
    finally:
        JOB_LOG_ID.reset(token)
