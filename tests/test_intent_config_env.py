"""环境变量默认兜底与 .env 加载。"""

from __future__ import annotations

from pathlib import Path

from autopilot.intent.config import (
    chat_model,
    intent_vision_enabled,
    intent_webhook_host,
    intent_webhook_port,
    vision_base_url,
    vision_model,
    vision_reasoning_effort,
    vision_temperature,
    vision_timeout_sec,
    vision_verbosity,
)
from autopilot.runtime.env_file import load_env_file


def test_intent_config_defaults(monkeypatch):
    for k in list(__import__("os").environ):
        if (
            k.startswith("AUTOPILOT_")
            or k.startswith("AP_AI_")
            or k.startswith("DEEPSEEK_")
            or k == "OPENAI_API_KEY"
        ):
            monkeypatch.delenv(k, raising=False)
    assert intent_vision_enabled() is False
    assert intent_webhook_host() == "127.0.0.1"
    assert intent_webhook_port() == 8765
    assert vision_base_url() == "https://api.openai.com/v1"
    assert vision_model() == "gpt-5.4-mini"
    assert vision_timeout_sec() == 45.0
    assert vision_reasoning_effort() == "none"
    assert vision_temperature() == 0.1
    assert vision_verbosity() == "none"


def test_intent_vision_not_auto_enabled_by_key(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_VISION", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert intent_vision_enabled() is False
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert intent_vision_enabled() is False
    monkeypatch.setenv("AUTOPILOT_INTENT_VISION", "1")
    assert intent_vision_enabled() is True


def test_chat_model_ignores_locate_and_vision_upgrade(monkeypatch):
    monkeypatch.delenv("AP_AI_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("AP_AI_LOCATE_MODEL", "deepseek-v4-pro")
    assert chat_model() == "deepseek-v4-flash"


def test_vision_model_deepseek_only_upgrade(monkeypatch):
    from autopilot.intent.config import vision_model
    from autopilot.intent.provider_profile import DEFAULT_DEEPSEEK_VISION_MODEL

    monkeypatch.delenv("AUTOPILOT_VISION_MODEL", raising=False)
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("AP_AI_MODEL", "gpt-5.4-mini")
    assert vision_model() == "gpt-5.4-mini"
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setenv("AP_AI_MODEL", "gemini-3.5-flash")
    assert vision_model() == "gemini-3.5-flash"
    monkeypatch.setenv(
        "AUTOPILOT_VISION_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("AP_AI_MODEL", "qwen-plus")
    assert vision_model() == "qwen-plus"
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    assert vision_model() == DEFAULT_DEEPSEEK_VISION_MODEL


def test_vision_temperature_verbosity_env(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_VISION_TEMPERATURE", "0.3")
    monkeypatch.setenv("AUTOPILOT_VISION_VERBOSITY", "medium")
    monkeypatch.setenv("AUTOPILOT_VISION_REASONING_EFFORT", "low")
    assert vision_temperature() == 0.3
    assert vision_verbosity() == "medium"
    assert vision_reasoning_effort() == "low"

    monkeypatch.delenv("AUTOPILOT_VISION_TEMPERATURE", raising=False)
    monkeypatch.delenv("AUTOPILOT_VISION_VERBOSITY", raising=False)
    monkeypatch.setenv("AP_AI_TEMPERATURE", "0.4")
    monkeypatch.setenv("AP_AI_VERBOSITY", "high")
    assert vision_temperature() == 0.4
    assert vision_verbosity() == "high"


def test_load_env_file_does_not_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_INTENT_VISION", "0")
    # load_env_file 直写 os.environ：先登记该键，既保证 override=False 可验证，
    # 也让 monkeypatch 在收尾时清掉，避免污染后续用例
    monkeypatch.delenv("AUTOPILOT_INTENT_WEBHOOK_PORT", raising=False)
    env = tmp_path / ".env"
    env.write_text("AUTOPILOT_INTENT_VISION=1\nAUTOPILOT_INTENT_WEBHOOK_PORT=9999\n", encoding="utf-8")
    assert load_env_file(env, override=False) is True
    assert __import__("os").environ["AUTOPILOT_INTENT_VISION"] == "0"
    assert __import__("os").environ["AUTOPILOT_INTENT_WEBHOOK_PORT"] == "9999"
