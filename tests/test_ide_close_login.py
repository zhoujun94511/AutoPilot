"""登录门禁与 resolve_login_project 单测。"""

from __future__ import annotations

import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("selenium")


def test_resolve_login_project_empty(monkeypatch):
    """无可见项目：允许进入 IDE，不弹选择器、不抛错。"""
    from autopilot.mgmt.project_context import resolve_login_project
    from autopilot.runtime import settings

    cleared: list[str] = []
    monkeypatch.setattr(settings, "mc_project_id", lambda: "stale")
    monkeypatch.setattr(
        settings, "set_mc_project_id", lambda v: cleared.append(str(v))
    )
    pid, need = resolve_login_project([])
    assert pid is None
    assert need is False
    assert cleared == [""]


def test_resolve_login_project_single():
    from autopilot.mgmt.project_context import resolve_login_project

    pid, need = resolve_login_project([{"id": "p1", "name": "One"}])
    assert pid == "p1"
    assert need is False


def test_resolve_login_project_remember_last(monkeypatch):
    from autopilot.mgmt.project_context import resolve_login_project
    from autopilot.runtime import settings

    monkeypatch.setattr(settings, "mc_project_id", lambda: "p2")
    monkeypatch.setattr(settings, "set_mc_project_id", lambda _v: None)
    projects = [
        {"id": "p1", "name": "A"},
        {"id": "p2", "name": "B"},
    ]
    pid, need = resolve_login_project(projects)
    assert pid == "p2"
    assert need is False


def test_resolve_login_project_need_picker(monkeypatch):
    from autopilot.mgmt.project_context import resolve_login_project
    from autopilot.runtime import settings

    cleared: list[str] = []
    monkeypatch.setattr(settings, "mc_project_id", lambda: "")
    monkeypatch.setattr(
        settings, "set_mc_project_id", lambda v: cleared.append(str(v))
    )
    pid, need = resolve_login_project(
        [{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}]
    )
    assert pid is None
    assert need is True


def test_login_gate_empty_projects_still_enters(monkeypatch):
    """无可见项目：登录成功后进入 IDE，不清会话。"""
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from autopilot.ui.widgets.mgmt_login_gate_dialog import MgmtLoginGateDialog

    saved: dict[str, str] = {"pid": "stale"}

    def fake_login(**_kwargs):
        return {"user": {"username": "u", "role": "operator"}}

    class _FakeClient:
        def __init__(self, *_a, **_k):
            pass

        def close(self):
            pass

    monkeypatch.setattr("autopilot.mgmt.login_and_persist", fake_login)
    monkeypatch.setattr("autopilot.mgmt.client.MgmtClient", _FakeClient)
    monkeypatch.setattr(
        "autopilot.mgmt.project_context.fetch_visible_projects",
        lambda _c: [],
    )
    monkeypatch.setattr("autopilot.runtime.settings.clear_mc_session", lambda: None)
    monkeypatch.setattr(
        "autopilot.runtime.settings.set_mc_project_id",
        lambda p: saved.__setitem__("pid", str(p)),
    )
    monkeypatch.setattr("autopilot.runtime.settings.mc_jwt", lambda: "tok")
    monkeypatch.setattr(
        "autopilot.runtime.settings.mc_server_url", lambda: "http://127.0.0.1:8000"
    )
    monkeypatch.setattr("autopilot.runtime.settings.mc_username", lambda: "u")
    monkeypatch.setattr("autopilot.runtime.settings.mc_password", lambda: "p")
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: saved["pid"])

    dlg = MgmtLoginGateDialog()
    dlg.url.setText("http://127.0.0.1:8000")
    dlg.username.setText("u")
    dlg.password.setText("p")
    dlg._do_login()
    assert dlg.logged_in is True
    assert saved["pid"] == ""


def test_login_gate_uses_worker(monkeypatch):
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    from autopilot.ui.widgets.mgmt_login_gate_dialog import MgmtLoginGateDialog

    calls: dict[str, int | str] = {"n": 0}

    def fake_login(**_kwargs):
        calls["n"] = int(calls["n"]) + 1
        calls["thread"] = threading.current_thread().name
        return {"user": {"username": "u", "role": "admin"}}

    class _FakeClient:
        def __init__(self, *_a, **_k):
            pass

        def close(self):
            pass

        @staticmethod
        def list_projects():
            return [{"id": "p1", "name": "P1"}]

    monkeypatch.setattr("autopilot.mgmt.login_and_persist", fake_login)
    monkeypatch.setattr("autopilot.mgmt.client.MgmtClient", _FakeClient)
    monkeypatch.setattr(
        "autopilot.mgmt.project_context.fetch_visible_projects",
        lambda _c: [{"id": "p1", "name": "P1"}],
    )
    monkeypatch.setattr("autopilot.runtime.settings.clear_mc_session", lambda: None)
    monkeypatch.setattr("autopilot.runtime.settings.set_mc_project_id", lambda _p: None)
    monkeypatch.setattr("autopilot.runtime.settings.mc_jwt", lambda: "tok")
    monkeypatch.setattr(
        "autopilot.runtime.settings.mc_server_url", lambda: "http://127.0.0.1:8000"
    )
    monkeypatch.setattr("autopilot.runtime.settings.mc_username", lambda: "u")
    monkeypatch.setattr("autopilot.runtime.settings.mc_password", lambda: "p")
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "")

    dlg = MgmtLoginGateDialog()
    dlg.url.setText("http://127.0.0.1:8000")
    dlg.username.setText("u")
    dlg.password.setText("p")
    dlg._do_login()
    assert calls["n"] == 1
    assert dlg.logged_in is True
    assert calls.get("thread") != threading.main_thread().name
