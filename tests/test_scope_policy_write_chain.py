"""三轮 ScopePolicy 改动的 IDE 白盒链路：映射确认、跨项目拦截、无项目启动 Runner。"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QMessageBox, QWidget  # noqa: E402


@pytest.fixture()
def qt_app():
    from tests._qt import get_qt_app

    return get_qt_app()


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
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


from autopilot.ui.main_window.mgmt_runner_web import MgmtRunnerWebMixin  # noqa: E402


class _RunnerHost(MgmtRunnerWebMixin, QWidget):
    """只挂载 Runner Mixin，补齐 Session Mixin 上的角色判定。"""

    def __init__(self):
        QWidget.__init__(self)
        self.console = SimpleNamespace(log=lambda *_a, **_k: None)
        self._local_runner = _Proc()
        self.refresh = 0

    @staticmethod
    def _mgmt_is_platform_admin() -> bool:
        from autopilot.ui.mgmt_role import is_platform_admin_role

        return is_platform_admin_role()

    def _mgmt_refresh_session_ui(self) -> None:
        self.refresh += 1

    def _mgmt_local_runner(self):
        return self._local_runner


def test_mapping_confirm_empty_inputs_rejected(qt_app, isolated_settings, monkeypatch):
    from autopilot.ui.main_window.mgmt_delivery import MgmtDeliveryMixin

    asked = {"n": 0}

    def boom(*_a, **_k):
        asked["n"] += 1
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(boom))
    h = MgmtDeliveryMixin()
    assert h._mgmt_confirm_project_mapping(project_dir="", project_id="p1", action="上传") is False
    assert h._mgmt_confirm_project_mapping(project_dir=".", project_id="", action="上传") is False
    assert asked["n"] == 0


def test_mapping_confirm_skips_when_already_bound(qt_app, tmp_path, isolated_settings, monkeypatch):
    from autopilot.ui.main_window.mgmt_delivery import MgmtDeliveryMixin

    asked = {"n": 0}

    def boom(*_a, **_k):
        asked["n"] += 1
        raise AssertionError("已绑定同项目不应再弹确认")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(boom))
    isolated_settings.set_mc_bound_project_id(str(tmp_path), "p-ok")
    h = MgmtDeliveryMixin()
    assert h._mgmt_confirm_project_mapping(
        project_dir=str(tmp_path), project_id="p-ok", action="上传工程"
    )
    assert asked["n"] == 0


def test_mapping_confirm_persists_after_yes(qt_app, tmp_path, isolated_settings, monkeypatch):
    from autopilot.ui.main_window.mgmt_delivery import MgmtDeliveryMixin

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_a, **_k: QMessageBox.StandardButton.Yes),
    )
    h = MgmtDeliveryMixin()
    assert isolated_settings.mc_bound_project_id(str(tmp_path)) == ""
    assert h._mgmt_confirm_project_mapping(
        project_dir=str(tmp_path), project_id="p-new", action="上传工程"
    )
    assert isolated_settings.mc_bound_project_id(str(tmp_path)) == "p-new"


def test_mapping_confirm_rejects_and_does_not_bind(qt_app, tmp_path, isolated_settings, monkeypatch):
    from autopilot.ui.main_window.mgmt_delivery import MgmtDeliveryMixin

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_a, **_k: QMessageBox.StandardButton.No),
    )
    h = MgmtDeliveryMixin()
    assert (
        h._mgmt_confirm_project_mapping(
            project_dir=str(tmp_path), project_id="p-no", action="导入逻辑用例"
        )
        is False
    )
    assert isolated_settings.mc_bound_project_id(str(tmp_path)) == ""


def test_sync_logical_case_blocks_cross_project(qt_app, tmp_path, isolated_settings, monkeypatch):
    from autopilot.ui.main_window.mgmt_delivery import MgmtDeliveryMixin

    isolated_settings.set_mc_project_id("p-current")
    warned = {"text": ""}

    def _warn(*args, **_k):
        warned["text"] = " ".join(str(x) for x in args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_warn))
    h = MgmtDeliveryMixin()
    h.project_dir = str(tmp_path)
    h._http_calls = 0
    h._mgmt_require_user_session = lambda **_k: True  # noqa: E731

    def _run_http(**_k):
        h._http_calls += 1

    h._mgmt_run_http = _run_http
    tc = SimpleNamespace(logical_case_id="lc-1", project_id="p-other", name="x")
    h._mgmt_sync_saved_logical_case(tc)
    assert "跨项目误写" in warned["text"]
    assert h._http_calls == 0


def test_admin_runner_start_without_project_issues_org_scope(
    qt_app, monkeypatch, isolated_settings
):
    calls = {"issue": []}

    class _FakeClient:
        @staticmethod
        def register_runner(payload):
            return payload

        @staticmethod
        def issue_scoped_runner_token(runner_id, *, org_id="", project_ids=None):
            calls["issue"].append(
                {
                    "runner_id": runner_id,
                    "org_id": org_id,
                    "project_ids": list(project_ids or []),
                }
            )
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
        lambda: "ide-local-1",
    )
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_local_devices",
        lambda: [],
    )

    h = _RunnerHost()
    h.mgmt_start_local_runner()
    assert calls["issue"] == [
        {"runner_id": "ide-local-1", "org_id": "org-scope", "project_ids": []}
    ]
    assert h._local_runner.started == [
        ("http://127.0.0.1:8000", "scoped-org-token", "ide-local-1")
    ]
    assert h.refresh == 1


def test_operator_runner_start_without_project_uses_preissued_token(
    qt_app, monkeypatch, isolated_settings
):
    calls = {"issue": 0}

    class _FakeClient:
        @staticmethod
        def register_runner(payload):
            return payload

        @staticmethod
        def issue_scoped_runner_token(*_a, **_k):
            calls["issue"] += 1
            return {"api_token": "nope"}

        def close(self):
            pass

    monkeypatch.setattr(
        "autopilot.mgmt.ensure_user_session",
        lambda **_k: (_FakeClient(), "jwt"),
    )
    monkeypatch.setattr(isolated_settings, "mc_server_url", lambda: "http://127.0.0.1:8000")
    monkeypatch.setattr(isolated_settings, "mc_project_id", lambda: "")
    monkeypatch.setattr(isolated_settings, "mc_org_id", lambda: "org-scope")
    monkeypatch.setattr(isolated_settings, "mc_user_role", lambda: "operator")
    monkeypatch.setattr(isolated_settings, "mc_api_token", lambda: "preissued-token")
    monkeypatch.setattr(
        "autopilot.mgmt.local_runner.default_local_runner_id",
        lambda: "ide-op-1",
    )
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_local_devices",
        lambda: [],
    )

    h = _RunnerHost()
    h.mgmt_start_local_runner()
    assert calls["issue"] == 0
    assert h._local_runner.started == [
        ("http://127.0.0.1:8000", "preissued-token", "ide-op-1")
    ]


def test_admin_runner_start_without_org_or_project_stops(
    qt_app, monkeypatch, isolated_settings
):
    infos = []

    def _info(*args, **_k):
        infos.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", staticmethod(_info))
    monkeypatch.setattr(isolated_settings, "mc_server_url", lambda: "http://127.0.0.1:8000")
    monkeypatch.setattr(isolated_settings, "mc_project_id", lambda: "")
    monkeypatch.setattr(isolated_settings, "mc_org_id", lambda: "")
    monkeypatch.setattr(isolated_settings, "mc_user_role", lambda: "admin")

    h = _RunnerHost()
    h.mgmt_start_local_runner()
    assert h._local_runner.started == []
    blob = " ".join(str(x) for x in infos)
    assert "组织 ID" in blob


def test_connect_persist_allows_empty_project(qt_app, isolated_settings, monkeypatch):
    isolated_settings.set_mc_project_id("stale-pid")
    from autopilot.ui.widgets.mgmt_connect_dialog import MgmtConnectDialog

    dlg = MgmtConnectDialog()
    dlg.project_id.setEditText("")
    dlg.org_id.setText("org-scope")
    dlg._persist_form(clear_session=False)
    assert isolated_settings.mc_project_id() == ""
    assert isolated_settings.mc_org_id() == "org-scope"


def test_write_gate_still_requires_cached_project(qt_app, isolated_settings, monkeypatch):
    isolated_settings.set_mc_project_id("")
    warned = []

    def _warn(*args, **_k):
        warned.append(args)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_warn))
    from autopilot.ui.main_window.mgmt_delivery import MgmtDeliveryMixin

    h = MgmtDeliveryMixin()
    assert h._mgmt_require_project_id(title="上传工程") == ""
    assert warned


def test_chat_platform_forwards_empty_project_id(monkeypatch, isolated_settings):
    captured = {}

    class _FakeClient:
        @staticmethod
        def ai_codegen(prompt, *, purpose="", project_id=""):
            captured["prompt"] = prompt
            captured["purpose"] = purpose
            captured["project_id"] = project_id
            return {"content": '{"steps":[]}'}

        def close(self):
            pass

    monkeypatch.setattr(isolated_settings, "mc_is_logged_in", lambda: True)
    monkeypatch.setattr(isolated_settings, "mc_project_id", lambda: "")
    monkeypatch.setattr(
        "autopilot.mgmt.auth_api.ensure_user_session",
        lambda: (_FakeClient(), "jwt"),
    )
    from autopilot.authoring.llm_client import chat_platform

    out = chat_platform("打开设置")
    assert '{"steps":[]}' in out
    assert captured["project_id"] == ""
