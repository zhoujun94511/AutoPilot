"""环境变量默认兜底与 .env 加载。"""

from __future__ import annotations

from pathlib import Path

from autopilot.intent.config import (
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
