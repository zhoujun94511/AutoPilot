"""Suite 结束 Appium 清理（UX-P2-003）。"""

from __future__ import annotations

from subprocess import Popen
from typing import cast

from autopilot.keywords.mobile.appium_server import (
    AppiumServer,
    register_started_appium_server,
    stop_started_appium_servers,
)


def test_register_and_stop_started_servers():
    srv = AppiumServer(host="127.0.0.1", port=47299)
    srv._proc = cast(Popen | None, object())  # noqa: SLF001 — 测试注册/清理，不真起进程
    register_started_appium_server(srv)
    stopped: list[bool] = []

    def _fake_stop() -> None:
        stopped.append(True)
        srv._proc = None  # noqa: SLF001

    srv.stop = _fake_stop  # type: ignore[method-assign]
    stop_started_appium_servers()
    assert stopped == [True]
    assert srv._proc is None


def test_run_cases_calls_appium_teardown(monkeypatch):
    from autopilot.engine import suite as suite_mod
    from autopilot.model.testcase import Shell, TestCase

    called: list[bool] = []

    def _fake_teardown(_base_vars):
        called.append(True)

    monkeypatch.setattr(suite_mod, "_teardown_suite_appium", _fake_teardown)
    monkeypatch.setattr(
        suite_mod,
        "Executor",
        type(
            "E",
            (),
            {
                "__init__": lambda *a, **k: None,
                "run_testcase": lambda self, testcase: type(
                    "RR", (), {"passed": True, "case_name": testcase.name, "results": []}
                )(),
            },
        ),
    )

    tc = TestCase(name="t")
    tc.case = Shell(name="main")
    suite_mod.run_cases([tc], name="s", base_vars={})
    assert called == [True]


def test_keep_appium_skips_stop_started_servers(monkeypatch):
    """B1-R-min：AUTOPILOT_RUNNER_KEEP_APPIUM=1 时不 stop 本进程 Appium。"""
    from autopilot.engine import suite as suite_mod

    monkeypatch.setenv("AUTOPILOT_RUNNER_KEEP_APPIUM", "1")
    stopped: list[bool] = []

    def _fake_stop() -> None:
        stopped.append(True)

    monkeypatch.setattr(
        "autopilot.keywords.mobile.appium_server.stop_started_appium_servers",
        _fake_stop,
    )
    suite_mod._teardown_suite_appium({})
    assert stopped == []


def test_teardown_without_device_does_not_kill_all_servers(monkeypatch):
    """无 UDID / 无 __appium_server__ 时不得清空本进程全部 Appium（并发 Job）。"""
    from autopilot.engine import suite as suite_mod

    monkeypatch.delenv("AUTOPILOT_RUNNER_KEEP_APPIUM", raising=False)
    stopped: list[bool] = []

    def _fake_stop() -> None:
        stopped.append(True)

    monkeypatch.setattr(
        "autopilot.keywords.mobile.appium_server.stop_started_appium_servers",
        _fake_stop,
    )
    suite_mod._teardown_suite_appium({})
    assert stopped == []
