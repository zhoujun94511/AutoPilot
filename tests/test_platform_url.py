"""IDE platform_url 与配置文档契约。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_platform_url_module():
    from autopilot.runtime.platform_url import platform_base_url

    url = platform_base_url(include_settings=False)
    assert url.startswith("http://")


def test_configuration_doc():
    text = (ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")
    assert "AUTOPILOT_PLATFORM_URL" in text
    assert "platform.url" in text


def test_runner_uses_platform_url():
    text = (ROOT / "autopilot" / "runner" / "__main__.py").read_text(encoding="utf-8")
    assert "platform_base_url" in text


def test_config_doctor_module():
    text = (ROOT / "tools" / "config_doctor.py").read_text(encoding="utf-8")
    assert "public/bootstrap" in text
    assert "platform_base_url" in text


def test_mc_server_url_matches_platform_base():
    from autopilot.runtime import settings
    from autopilot.runtime.platform_url import platform_base_url

    assert settings.mc_server_url() == platform_base_url()
    assert settings.mc_server_url().startswith("http://")


def test_deploy_platform_url_locks(monkeypatch):
    from autopilot.runtime.platform_deploy import (
        deploy_platform_url,
        platform_url_locked,
    )
    from autopilot.runtime.platform_url import platform_base_url

    deploy_platform_url.cache_clear()
    monkeypatch.setenv("AUTOPILOT_PLATFORM_URL", "https://corp.example.com")
    deploy_platform_url.cache_clear()
    assert deploy_platform_url() == "https://corp.example.com"
    assert platform_url_locked() is True
    assert platform_base_url() == "https://corp.example.com"
    deploy_platform_url.cache_clear()
