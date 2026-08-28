"""AUD-2026-10：adb shell 命令面 — 插值校验与审计入口。"""

from __future__ import annotations

import pytest

from autopilot.mobile import adb


def test_require_adb_shell_safe_token_accepts_getprop_key():
    assert adb.require_adb_shell_safe_token("ro.build.version.sdk") == "ro.build.version.sdk"


@pytest.mark.parametrize(
    "bad",
    ["ro;rm -rf", "a b", "x`id`", "y$(id)", "z|w", ""],
)
def test_require_adb_shell_safe_token_rejects_meta(bad):
    with pytest.raises(ValueError, match="AUD-2026-10"):
        adb.require_adb_shell_safe_token(bad)


def test_require_android_package():
    assert adb.require_android_package("com.demo.app") == "com.demo.app"
    with pytest.raises(ValueError, match="AUD-2026-10"):
        adb.require_android_package("com.demo;reboot")


def test_require_adb_input_safe_text():
    assert adb.require_adb_input_safe_text("hello world") == "hello world"
    with pytest.raises(ValueError, match="AUD-2026-10"):
        adb.require_adb_input_safe_text("hi;reboot")


def test_adb_shell_audits_and_delegates(monkeypatch):
    seen: list[str] = []

    def _fake_run(args, serial="", timeout=30):
        _ = serial, timeout
        seen.append(" ".join(args))
        return "ok"

    monkeypatch.setattr(adb, "run_adb", _fake_run)
    logs: list[str] = []
    monkeypatch.setattr(
        adb._log, "info", lambda fmt, *a: logs.append(fmt % a if a else fmt)
    )
    assert adb.adb_shell("dumpsys window", serial="S1") == "ok"
    assert any("shell" in s and "dumpsys window" in s for s in seen)
    assert any("AUD-2026-10" in m for m in logs)


def test_assert_adb_invocation_allows_host_cmds():
    adb.assert_adb_invocation(["devices", "-l"])
    adb.assert_adb_invocation(["reconnect", "offline"])
    adb.assert_adb_invocation(["shell", "getprop", "ro.build.version.sdk"], serial="S1")
    adb.assert_adb_invocation(["-s", "S1", "shell", "getprop", "ro.build.version.sdk"])


def test_assert_adb_invocation_rejects_kill_server():
    with pytest.raises(RuntimeError, match="kill-server"):
        adb.assert_adb_invocation(["kill-server"])


def test_assert_adb_invocation_requires_serial_for_device_cmds():
    with pytest.raises(RuntimeError, match="serial"):
        adb.assert_adb_invocation(["shell", "getprop", "ro.build.version.sdk"])
