"""IDE Refresh Token：登录持久化、续期优先于密码重登、登出吊销。"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from autopilot.mgmt.auth_api import (
    ensure_user_session,
    login_and_persist,
    logout_and_clear,
    persist_token_pair,
    refresh_and_persist,
)
from autopilot.mgmt.client import MgmtClientError


@pytest.fixture()
def mc_settings(monkeypatch, tmp_path):
    store: dict[str, object] = {
        "mc_server_url": "http://127.0.0.1:8000",
        "mc_username": "alice",
        "mc_password": "Secret12",
        "mc_jwt": "",
        "mc_refresh": "",
        "mc_user_id": "",
        "mc_user_role": "",
        "mc_api_token": "",
    }

    def load():
        return dict(store)

    def set_value(key, value):
        store[key] = value

    monkeypatch.setattr("autopilot.runtime.settings.load", load)
    monkeypatch.setattr("autopilot.runtime.settings.set_value", set_value)
    monkeypatch.setattr(
        "autopilot.runtime.settings.save",
        lambda data: (store.clear(), store.update(data)),
    )
    # 直接走 getters/setters 所用路径
    import autopilot.runtime.settings as settings

    monkeypatch.setattr(settings, "load", load)
    monkeypatch.setattr(settings, "set_value", set_value)
    return store


def test_persist_token_pair(mc_settings):
    from autopilot.runtime import settings

    persist_token_pair(
        {
            "access_token": "acc1",
            "refresh_token": "ref1",
            "user": {"id": "u1", "username": "alice", "role": "operator"},
        }
    )
    assert settings.mc_jwt() == "acc1"
    assert settings.mc_refresh() == "ref1"
    assert settings.mc_user_id() == "u1"
    assert "mc_refresh" not in mc_settings
    assert str(mc_settings.get("mc_refresh_enc") or "").startswith("v1:")
    assert "ref1" not in str(mc_settings.get("mc_refresh_enc"))


def test_login_and_persist_saves_refresh(mc_settings, monkeypatch):
    from autopilot.runtime import settings

    monkeypatch.setattr(
        "autopilot.mgmt.auth_api.api_login",
        lambda *_a, **_k: {
            "access_token": "a2",
            "refresh_token": "r2",
            "user": {"id": "u2", "username": "alice", "role": "admin"},
        },
    )
    out = login_and_persist()
    assert out["refresh_token"] == "r2"
    assert settings.mc_jwt() == "a2"
    assert settings.mc_refresh() == "r2"
    assert settings.mc_user_role() == "admin"


def test_refresh_and_persist_rotates(mc_settings, monkeypatch):
    from autopilot.runtime import settings

    settings.set_mc_refresh("old-rt")
    monkeypatch.setattr(
        "autopilot.mgmt.auth_api.api_refresh",
        lambda *_a, **_k: {
            "access_token": "a3",
            "refresh_token": "new-rt",
            "user": {"id": "u3", "username": "alice", "role": "operator"},
        },
    )
    refresh_and_persist()
    assert settings.mc_jwt() == "a3"
    assert settings.mc_refresh() == "new-rt"


def test_ensure_user_session_prefers_refresh_on_401(mc_settings, monkeypatch):
    from autopilot.runtime import settings

    settings.set_mc_jwt("stale")
    settings.set_mc_refresh("good-rt")
    calls = {"refresh": 0, "login": 0}

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def me(self):
            raise MgmtClientError("登录已失效", status_code=401)

        def close(self):
            pass

    def fake_refresh(**_k):
        calls["refresh"] += 1
        settings.set_mc_jwt("fresh")
        settings.set_mc_refresh("rotated")
        return {"access_token": "fresh", "refresh_token": "rotated"}

    def fake_login(**_k):
        calls["login"] += 1
        settings.set_mc_jwt("from-pwd")
        return {"access_token": "from-pwd"}

    monkeypatch.setattr("autopilot.mgmt.auth_api.MgmtClient", _Client)
    monkeypatch.setattr("autopilot.mgmt.auth_api.refresh_and_persist", fake_refresh)
    monkeypatch.setattr("autopilot.mgmt.auth_api.login_and_persist", fake_login)

    # 第二次 me 会成功：换一个可切换的 client
    state = {"n": 0}

    class _Client2:
        def __init__(self, *_a, **_k):
            pass

        @staticmethod
        def me():
            state["n"] += 1
            if state["n"] == 1:
                raise MgmtClientError("登录已失效", status_code=401)
            return {"id": "u", "username": "alice", "role": "operator"}

        def close(self):
            pass

    monkeypatch.setattr("autopilot.mgmt.auth_api.MgmtClient", _Client2)
    client, jwt = ensure_user_session(require=True)
    try:
        assert jwt == "fresh"
        assert calls["refresh"] == 1
        assert calls["login"] == 0
        assert settings.mc_refresh() == "rotated"
    finally:
        client.close()


def test_logout_and_clear_revokes(mc_settings, monkeypatch):
    from autopilot.runtime import settings

    settings.set_mc_jwt("acc")
    settings.set_mc_refresh("rt-x")
    seen = {"rt": ""}

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        @staticmethod
        def logout(refresh_token=""):
            seen["rt"] = refresh_token

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def close(self):
            pass

    monkeypatch.setattr("autopilot.mgmt.auth_api.MgmtClient", _Client)
    logout_and_clear()
    assert seen["rt"] == "rt-x"
    assert settings.mc_jwt() == ""
    assert settings.mc_refresh() == ""
