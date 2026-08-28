"""管理台连接相关：密码加密、Web 基址。"""

from __future__ import annotations

import os


def _isolate_mc_keyring(monkeypatch):
    """测试只走 settings.json / DPAPI|Fernet，避免本机 keyring 污染。"""
    monkeypatch.setattr(
        "autopilot.runtime.settings._mc_keyring_get", lambda _user: None
    )
    monkeypatch.setattr(
        "autopilot.runtime.settings._mc_keyring_store", lambda _user, _pwd: False
    )
    monkeypatch.setattr(
        "autopilot.runtime.settings._secret_keyring_get", lambda _kind: None
    )
    monkeypatch.setattr(
        "autopilot.runtime.settings._secret_keyring_store",
        lambda _kind, _value: False,
    )


def test_mc_password_encrypted_not_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path))
    from autopilot.runtime import settings

    _isolate_mc_keyring(monkeypatch)
    settings.set_mc_password("secret-pass")
    import json

    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "secret-pass" not in json.dumps(data)
    assert "mc_password_enc" in data
    assert "mc_password" not in data
    assert settings.mc_password() == "secret-pass"

    settings.set_mc_password("")
    assert settings.mc_password() == ""


def test_mc_jwt_and_api_token_encrypted(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path))
    from autopilot.runtime import settings

    _isolate_mc_keyring(monkeypatch)
    settings.set_mc_jwt("eyJhbGciOiJIUzI1NiJ9.payload.sig")
    settings.set_mc_api_token("runner-secret-token")
    import json
    import sys

    raw = (tmp_path / "settings.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "eyJhbGciOiJIUzI1NiJ9" not in raw
    assert "runner-secret-token" not in raw
    assert "mc_jwt_enc" in data
    assert "mc_api_token_enc" in data
    assert "mc_jwt" not in data
    assert "mc_api_token" not in data
    assert settings.mc_jwt().startswith("eyJ")
    assert settings.mc_api_token() == "runner-secret-token"
    # Windows：优先 DPAPI；其它平台仍 Fernet v1
    prefix = "v2dpapi:" if sys.platform == "win32" else "v1:"
    assert str(data["mc_jwt_enc"]).startswith(prefix)
    assert str(data["mc_api_token_enc"]).startswith(prefix)


def test_mc_jwt_migrates_legacy_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path))
    from autopilot.runtime import settings

    _isolate_mc_keyring(monkeypatch)
    settings.save({"mc_jwt": "legacy-jwt", "mc_api_token": "legacy-tok"})
    assert settings.mc_jwt() == "legacy-jwt"
    assert settings.mc_api_token() == "legacy-tok"
    raw = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "legacy-jwt" not in raw
    assert "legacy-tok" not in raw
    assert "mc_jwt_enc" in raw
    assert "mc_api_token_enc" in raw


def test_mc_password_migrates_legacy_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path))
    from autopilot.runtime import settings

    _isolate_mc_keyring(monkeypatch)
    settings.save({"mc_password": "legacy-plain"})
    assert settings.mc_password() == "legacy-plain"
    raw = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "legacy-plain" not in raw
    assert "mc_password_enc" in raw


def test_settings_file_permissions_hardened(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path))
    from autopilot.runtime import settings

    _isolate_mc_keyring(monkeypatch)
    settings.set_mc_api_token("tok")
    path = tmp_path / "settings.json"
    assert path.is_file()
    if os.name == "posix":
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600


def test_dpapi_roundtrip_on_windows():
    import sys

    if sys.platform != "win32":
        return
    from autopilot.runtime import settings

    blob = settings._dpapi_protect(b"hello-dpapi")
    assert blob
    assert settings._dpapi_unprotect(blob) == b"hello-dpapi"


def test_resolve_web_frontend_url_prefers_live_vite():
    from autopilot.mgmt.web_frontend import resolve_web_frontend_url

    api = "http://127.0.0.1:8000"
    assert (
        resolve_web_frontend_url(
            api_url=api, configured_web="http://console.example", vite_open=lambda _h: True
        )
        == "http://console.example"
    )
    assert (
        resolve_web_frontend_url(api_url=api, env={"AUTOPILOT_MC_DEV_WEB": "0"}, vite_open=lambda _h: True)
        == api
    )
    assert (
        resolve_web_frontend_url(api_url=api, env={"AUTOPILOT_MC_DEV_WEB": "1"}, vite_open=lambda _h: False)
        == "http://127.0.0.1:5173"
    )
    assert (
        resolve_web_frontend_url(api_url=api, env={}, vite_open=lambda _h: True)
        == "http://127.0.0.1:5173"
    )
    assert resolve_web_frontend_url(api_url=api, env={}, vite_open=lambda _h: False) == api
    assert (
        resolve_web_frontend_url(
            api_url="https://autopilot.example.com", env={}, vite_open=lambda _h: True
        )
        == "https://autopilot.example.com"
    )


def test_mgmt_web_base_url_follows_resolver(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_MC_DEV_WEB", raising=False)
    from autopilot.runtime import settings
    from autopilot.ui.main_window.mgmt import MgmtMixin

    monkeypatch.setattr(settings, "mc_web_url", lambda: "", raising=False)
    monkeypatch.setattr(settings, "mc_server_url", lambda: "http://127.0.0.1:8000")
    monkeypatch.setattr(
        "autopilot.mgmt.web_frontend.vite_port_open", lambda _host, **_kw: False
    )
    assert MgmtMixin._mgmt_web_base_url() == "http://127.0.0.1:8000"

    monkeypatch.setenv("AUTOPILOT_MC_DEV_WEB", "1")
    assert MgmtMixin._mgmt_web_base_url() == "http://127.0.0.1:5173"


def test_submit_dialog_requires_parallel_for_multi_udid(_qtbot=None):
    """无 Qt display 时跳过；有显示时校验多设备必须并行。"""
    if os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        return
    _ = QApplication.instance() or QApplication([])
    from autopilot.ui.widgets.mgmt_submit_job_dialog import MgmtSubmitJobDialog

    dlg = MgmtSubmitJobDialog(None, devices=[])
    dlg.udids.setText("a, b")
    dlg.parallel.setChecked(False)
    try:
        dlg.values()
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "并行" in str(exc)
    dlg.parallel.setChecked(True)
    vals = dlg.values()
    assert vals["parallel"] is True
    assert vals["device_udids"] == ["a", "b"]
    assert "backend_mode" in vals
    assert "wda_bundle" in vals
    dlg.close()
    del _
