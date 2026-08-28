"""Windows GUI 进程下子进程不得弹控制台窗口（左上角闪黑框）。

根因：打包后的 IDE / ``pythonw run.py`` 没有父控制台，裸 ``subprocess`` 会为
``adb.exe`` / ``icacls.exe`` 等控制台程序新建 conhost 窗口并一闪而过。设备监控每 3s
一次、写 settings 每次两次 icacls，登录等待时尤其显眼。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from autopilot.runtime import subproc

# 允许直接调用裸 subprocess 的文件及原因
_SPAWN_ALLOWLIST = {
    # helper 自身
    "autopilot/runtime/subproc.py",
    # 通过 kwargs 变量显式设置 creationflags（含 CREATE_NO_WINDOW）
    "autopilot/mgmt/local_runner.py",
    "autopilot/mobile/ios_screen_record.py",
    # 启动的是 GUI 程序（explorer / open / xdg-open），本身不带控制台
    "autopilot/ui/main_window/files.py",
    # macOS 专用路径（AVFoundation helper / xattr），不在 Windows 上执行
    "autopilot/inspector/stream/avf_source.py",
    "autopilot/mobile/adb.py",
}
_SPAWN_ATTRS = {"run", "Popen", "check_output", "call", "check_call"}


def _iter_py_files():
    for base, dirs, files in os.walk(os.path.join(ROOT, "autopilot")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(base, name)
                yield path, os.path.relpath(path, ROOT).replace(os.sep, "/")


def _bare_spawn_calls(source: str) -> list[str]:
    """返回 ``subprocess.<spawn>()`` 且未显式带 creationflags 的调用点。"""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _SPAWN_ATTRS:
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "subprocess":
            continue
        if any(kw.arg == "creationflags" for kw in node.keywords):
            continue
        hits.append(f"line {node.lineno}: subprocess.{func.attr}(...)")
    return hits


def test_no_bare_subprocess_spawn_outside_allowlist():
    """新增 spawn 点必须走 autopilot.runtime.subproc，否则 Windows 下会闪窗。"""
    offenders: dict[str, list[str]] = {}
    for path, rel in _iter_py_files():
        if rel in _SPAWN_ALLOWLIST:
            continue
        with open(path, encoding="utf-8") as fh:
            hits = _bare_spawn_calls(fh.read())
        if hits:
            offenders[rel] = hits
    assert not offenders, (
        "以下位置直接调用了 subprocess，Windows GUI 进程下会闪控制台窗口；"
        f"请改用 autopilot.runtime.subproc：{offenders}"
    )


def test_allowlisted_spawn_files_still_handle_windows():
    """白名单里声称「自己处理」的文件，必须真的设置了 creationflags。"""
    for rel in ("autopilot/mgmt/local_runner.py", "autopilot/mobile/ios_screen_record.py"):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            src = fh.read()
        assert "CREATE_NO_WINDOW" in src, rel
        assert "creationflags" in src, rel


def test_hidden_kwargs_adds_no_window_on_windows(monkeypatch):
    monkeypatch.setattr(subproc.sys, "platform", "win32")
    assert subproc.hidden_kwargs()["creationflags"] == subproc.CREATE_NO_WINDOW
    got = subproc.hidden_kwargs({"capture_output": True})
    assert got["capture_output"] is True
    assert got["creationflags"] == subproc.CREATE_NO_WINDOW


def test_hidden_kwargs_preserves_existing_flags(monkeypatch):
    monkeypatch.setattr(subproc.sys, "platform", "win32")
    got = subproc.hidden_kwargs({"creationflags": subproc.CREATE_NEW_PROCESS_GROUP})
    assert got["creationflags"] & subproc.CREATE_NEW_PROCESS_GROUP
    assert got["creationflags"] & subproc.CREATE_NO_WINDOW


@pytest.mark.parametrize(
    "flag",
    [
        getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
        getattr(subprocess, "DETACHED_PROCESS", 0x00000008),
    ],
)
def test_hidden_kwargs_respects_explicit_console_intent(monkeypatch, flag):
    """调用方明确要新建/脱离控制台时不得强塞 CREATE_NO_WINDOW（二者互斥）。"""
    monkeypatch.setattr(subproc.sys, "platform", "win32")
    got = subproc.hidden_kwargs({"creationflags": flag})
    assert got["creationflags"] == flag


def test_hidden_kwargs_noop_off_windows(monkeypatch):
    monkeypatch.setattr(subproc.sys, "platform", "linux")
    assert "creationflags" not in subproc.hidden_kwargs({"capture_output": True})


def test_run_and_popen_forward_hidden_kwargs(monkeypatch):
    monkeypatch.setattr(subproc.sys, "platform", "win32")
    seen: dict[str, dict] = {}

    monkeypatch.setattr(
        subproc.subprocess, "run", lambda cmd, **kw: seen.setdefault("run", kw)
    )
    monkeypatch.setattr(
        subproc.subprocess, "Popen", lambda cmd, **kw: seen.setdefault("popen", kw)
    )
    subproc.run(["x"], capture_output=True)
    subproc.popen(["x"])
    assert seen["run"]["creationflags"] == subproc.CREATE_NO_WINDOW
    assert seen["popen"]["creationflags"] == subproc.CREATE_NO_WINDOW


def test_run_adb_goes_through_hidden_runner(monkeypatch):
    """设备监控每 3s 调一次 adb devices —— 闪窗的高频来源，必须走 helper。"""
    from autopilot.mobile import adb

    class _Result:
        returncode = 0
        stdout = b"List of devices attached\n"
        stderr = b""

    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(adb, "ensure_adb", lambda: "adb")
    monkeypatch.setattr(subproc, "run", fake_run)
    monkeypatch.setattr(
        subproc.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("run_adb 绕过了 subproc.run"),
    )
    out = adb.run_adb(["devices"])
    assert "List of devices attached" in out
    assert seen["cmd"] == ["adb", "devices"]


def test_settings_harden_permissions_goes_through_hidden_runner(monkeypatch, tmp_path):
    """写 settings 会跑两次 icacls；登录必写 → 曾是「登录瞬间闪框」的直接来源。"""
    from autopilot.runtime import settings

    if sys.platform != "win32":
        pytest.skip("icacls 仅 Windows")

    target = tmp_path / "settings.json"
    target.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(subproc, "run", lambda cmd, **_k: calls.append(list(cmd)))
    monkeypatch.setattr(
        subproc.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("_harden_path_permissions 绕过了 subproc.run"),
    )
    settings._harden_path_permissions(str(target), is_dir=False)
    assert [c[0] for c in calls] == ["icacls", "icacls"]
