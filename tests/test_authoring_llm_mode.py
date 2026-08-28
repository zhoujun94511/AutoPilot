"""链路 3 LLM 模式：企业锁定 URL 默认 platform；显式 env 优先。"""

from __future__ import annotations

import pytest

from autopilot.authoring.llm_client import llm_mode
from autopilot.runtime.platform_deploy import deploy_platform_url


@pytest.fixture(autouse=True)
def _clear_deploy_cache():
    deploy_platform_url.cache_clear()
    yield
    deploy_platform_url.cache_clear()


def test_llm_mode_explicit_local_wins_over_locked_url(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_PLATFORM_URL", "https://corp.example.com")
    monkeypatch.setenv("AUTOPILOT_AUTHORING_LLM_MODE", "local")
    deploy_platform_url.cache_clear()
    assert llm_mode() == "local"


def test_llm_mode_explicit_platform(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_PLATFORM_URL", raising=False)
    monkeypatch.setenv("AUTOPILOT_AUTHORING_LLM_MODE", "platform")
    deploy_platform_url.cache_clear()
    assert llm_mode() == "platform"


def test_llm_mode_locked_url_defaults_platform(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_AUTHORING_LLM_MODE", raising=False)
    monkeypatch.setenv("AUTOPILOT_PLATFORM_URL", "https://corp.example.com")
    monkeypatch.delenv("AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE", raising=False)
    deploy_platform_url.cache_clear()
    assert llm_mode() == "platform"


def test_llm_mode_unlocked_defaults_local(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_AUTHORING_LLM_MODE", raising=False)
    monkeypatch.delenv("AUTOPILOT_PLATFORM_URL", raising=False)
    monkeypatch.delenv("AUTOPILOT_PLATFORM_URL_FILE", raising=False)
    monkeypatch.setattr("autopilot.runtime.settings.mc_is_logged_in", lambda: False)
    deploy_platform_url.cache_clear()
    assert llm_mode() == "local"


def test_llm_mode_logged_in_defaults_platform(monkeypatch):
    """平台已登录就用平台持钥；不要求部署 URL 被企业锁定。"""
    monkeypatch.delenv("AUTOPILOT_AUTHORING_LLM_MODE", raising=False)
    monkeypatch.delenv("AUTOPILOT_PLATFORM_URL", raising=False)
    monkeypatch.delenv("AUTOPILOT_PLATFORM_URL_FILE", raising=False)
    monkeypatch.setattr("autopilot.runtime.settings.mc_is_logged_in", lambda: True)
    deploy_platform_url.cache_clear()
    assert llm_mode() == "platform"
