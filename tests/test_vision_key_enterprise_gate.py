"""AUD-P2-007：企业锁定 URL 时默认禁用本机 Vision Key。"""

from __future__ import annotations


def test_vision_key_blocked_when_platform_url_locked(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_PLATFORM_URL", "https://autopilot.example.com")
    monkeypatch.delenv("AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE", raising=False)
    monkeypatch.delenv("AUTOPILOT_VISION_ALLOW_LOCAL_KEY", raising=False)
    monkeypatch.setenv("AUTOPILOT_VISION_API_KEY", "sk-vision")

    from autopilot.runtime.platform_deploy import deploy_platform_url, platform_url_locked

    deploy_platform_url.cache_clear()
    assert platform_url_locked() is True

    from autopilot.intent import config as cfg

    assert cfg.vision_api_key_configured() is True
    assert cfg.vision_local_key_allowed() is False
    assert cfg.vision_api_key() == ""


def test_vision_key_allowed_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_PLATFORM_URL", "https://autopilot.example.com")
    monkeypatch.delenv("AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE", raising=False)
    monkeypatch.setenv("AUTOPILOT_VISION_ALLOW_LOCAL_KEY", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    monkeypatch.delenv("AUTOPILOT_VISION_API_KEY", raising=False)
    monkeypatch.delenv("AP_AI_API_KEY", raising=False)

    from autopilot.runtime.platform_deploy import deploy_platform_url

    deploy_platform_url.cache_clear()

    from autopilot.intent import config as cfg

    assert cfg.vision_local_key_allowed() is True
    assert cfg.vision_api_key() == "sk-ds"


def test_vision_key_ok_when_unlocked_dev(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_PLATFORM_URL", raising=False)
    monkeypatch.delenv("AUTOPILOT_VISION_ALLOW_LOCAL_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.delenv("AUTOPILOT_VISION_API_KEY", raising=False)
    monkeypatch.delenv("AP_AI_API_KEY", raising=False)

    from autopilot.runtime.platform_deploy import deploy_platform_url

    deploy_platform_url.cache_clear()

    from autopilot.intent import config as cfg

    assert cfg.vision_local_key_allowed() is True
    assert cfg.vision_api_key() == "sk-oai"
