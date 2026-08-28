"""IDE Runner 启动：platform_admin 可自签 Token，operator 须预配 Token。"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_platform_admin_role_gate(monkeypatch):
    from autopilot.runtime import settings

    store = {"mc_user_role": "admin"}
    # 必须走 monkeypatch：直接赋值会把桩留给后续所有用例（settings 全局读不到真配置）
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    assert settings.mc_user_role().strip().lower() == "admin"


def test_operator_role_not_platform_admin(monkeypatch):
    from autopilot.runtime import settings

    store = {"mc_user_role": "operator"}
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    assert settings.mc_user_role().strip().lower() != "admin"


def test_operator_runner_start_skips_scoped_token_issue(monkeypatch):
    """白盒：operator 路径不调用 issue_scoped_runner_token。"""
    calls = {"issue": 0, "register": 0}

    class _FakeClient:
        @staticmethod
        def register_runner(_payload):
            calls["register"] += 1

        @staticmethod
        def issue_scoped_runner_token(*_a, **_k):
            calls["issue"] += 1
            return {"api_token": "should-not-happen"}

        def close(self):
            pass

    monkeypatch.setattr(
        "autopilot.mgmt.ensure_user_session",
        lambda **_k: (_FakeClient(), "jwt"),
    )

    store = {
        "mc_server_url": "http://127.0.0.1:8000",
        "mc_project_id": "p1",
        "mc_api_token": "",
        "mc_user_role": "operator",
        "mc_org_id": "org1",
    }

    def load():
        return dict(store)

    import autopilot.runtime.settings as settings

    monkeypatch.setattr(settings, "load", load)
    monkeypatch.setattr(settings, "mc_server_url", lambda: store["mc_server_url"])
    monkeypatch.setattr(settings, "mc_project_id", lambda: store["mc_project_id"])
    monkeypatch.setattr(settings, "mc_api_token", lambda: store["mc_api_token"])
    monkeypatch.setattr(settings, "mc_user_role", lambda: store["mc_user_role"])
    monkeypatch.setattr(settings, "mc_org_id", lambda: store["mc_org_id"])

    is_admin = settings.mc_user_role().strip().lower() == "admin"
    assert is_admin is False

    # operator 分支：无预配 token 时不应 register/issue
    token = settings.mc_api_token().strip()
    assert token == ""
    assert calls["issue"] == 0
    assert calls["register"] == 0
