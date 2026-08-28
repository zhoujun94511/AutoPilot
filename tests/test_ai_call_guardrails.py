"""IDE 侧 AI 调用护栏：调用前预检 / prompt 上限 / Vision 每用例硬顶。"""

from __future__ import annotations

import pytest

from autopilot.authoring.contract import AuthoringError
from autopilot.authoring.llm_client import MAX_PROMPT_CHARS, assert_llm_ready, complete_json
from autopilot.authoring.prompt import (
    MAX_ELEMENTS_CHARS,
    MAX_HISTORY_ITEMS,
    build_agent_turn_prompt,
)
from autopilot.intent import vision


def test_platform_mode_requires_login(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_LLM_MODE", "platform")
    monkeypatch.setattr("autopilot.runtime.settings.mc_is_logged_in", lambda: False)
    with pytest.raises(AuthoringError, match="登录管理台"):
        assert_llm_ready()

    monkeypatch.setattr("autopilot.runtime.settings.mc_is_logged_in", lambda: True)
    monkeypatch.setattr(
        "autopilot.authoring.llm_client.platform_llm_capabilities",
        lambda: {
            "enabled": True,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "accepts_images": False,
        },
    )
    assert assert_llm_ready() == "platform"


def test_local_mode_requires_key(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_LLM_MODE", "local")
    monkeypatch.setattr("autopilot.authoring.llm_client.vision_api_key", lambda: "")
    with pytest.raises(AuthoringError, match="AI 服务尚未就绪"):
        assert_llm_ready()

    monkeypatch.setattr("autopilot.authoring.llm_client.vision_api_key", lambda: "sk-x")
    assert assert_llm_ready() == "local"


def test_oversized_prompt_not_sent():
    calls: list[str] = []

    def chat(prompt: str) -> str:
        calls.append(prompt)
        return "{}"

    with pytest.raises(AuthoringError, match="内容过多|拆成更小"):
        complete_json("x" * (MAX_PROMPT_CHARS + 1), chat=chat)
    assert not calls, "超长 prompt 不应发出请求"


def test_agent_turn_prompt_trims_context():
    history = [{"keyword_id": f"kw_{i}", "params": {}} for i in range(30)]
    prompt = build_agent_turn_prompt(
        natural_language="搜索 cat",
        platform="ios",
        elements_text="e" * (MAX_ELEMENTS_CHARS + 5000),
        keyword_catalog=[{"id": "mobile_element_click"}],
        history=history,
        remaining_steps=4,
    )
    assert "kw_29" in prompt
    assert f"kw_{30 - MAX_HISTORY_ITEMS - 1}" not in prompt
    # 超长摘要不得做字符级截断（会破坏 JSON）；兜底为空数组
    assert "eeeeeeee" not in prompt
    assert "[]" in prompt
    assert len(prompt) < MAX_PROMPT_CHARS


def test_vision_calls_capped_per_case(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_INTENT_VISION", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_MAX_CALLS_PER_CASE", "2")
    calls: list[int] = []

    def fake_propose(**_kwargs):
        calls.append(1)
        return [{"keyword_id": "mobile_element_click"}]

    from autopilot.intent import vision_plugin

    monkeypatch.setattr(vision_plugin, "propose_candidates", fake_propose)
    vision.reset_vision_call_budget()

    for _ in range(5):
        vision.vision_candidates(action="click", target="搜索", value="", platform="ios")
    assert len(calls) == 2, "超过每用例上限后不应再调用 vision"
    assert vision.vision_calls_used() == 2

    vision.reset_vision_call_budget()
    vision.vision_candidates(action="click", target="搜索", value="", platform="ios")
    assert len(calls) == 3, "新用例应重置额度"
