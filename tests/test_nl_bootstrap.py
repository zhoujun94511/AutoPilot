"""NL bootstrap：显式槽位 → LLM → 正则。"""

from __future__ import annotations

import json

from autopilot.authoring.contract import AuthoringError
from autopilot.authoring.nl_bootstrap import (
    explicit_hints,
    extract_nl_hints_via_llm,
    hints_sufficient,
    merge_nl_hints,
    resolve_nl_hints,
)
from autopilot.authoring.nl_parse import NlHints, parse_nl_hints


def test_merge_prefers_later_non_empty():
    a = NlHints(platform="ios", app_name="A")
    b = NlHints(app_name="B", package_name="com.b")
    m = merge_nl_hints(a, b)
    assert m.platform == "ios"
    assert m.app_name == "B"
    assert m.package_name == "com.b"


def test_explicit_slots_skip_llm(monkeypatch):
    calls: list[str] = []

    def boom(_prompt: str) -> str:
        calls.append("x")
        return "{}"

    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    hints, notes = resolve_nl_hints(
        "用自然语言随便写一点含糊描述",
        platform="ios",
        package_name="com.acme.demo",
        chat=boom,
        allow_llm=True,
    )
    assert hints.platform == "ios"
    assert hints.package_name == "com.acme.demo"
    assert calls == []
    assert any(n.startswith("nl:") for n in notes)


def test_regex_fallback_when_llm_disabled(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "0")
    hints, notes = resolve_nl_hints(
        "打开iOS手机上的设置应用，进入无线局域网",
        allow_llm=True,
    )
    assert hints.platform == "ios"
    assert hints.app_name == "设置"
    assert "nl:regex" in notes or "nl:partial" in notes


def test_llm_extract_fills_ambiguous_nl(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    # 是否放行 LLM 取决于本机登录/Key，测试里必须固定住
    monkeypatch.setattr(
        "autopilot.authoring.nl_bootstrap._nl_llm_enabled", lambda: True
    )

    def chat(_prompt: str) -> str:
        return json.dumps(
            {
                "platform": "android",
                "app_name": "天气助手",
                "package_name": "",
                "start_url": "",
                "input_texts": ["北京"],
            },
            ensure_ascii=False,
        )

    hints, notes = resolve_nl_hints(
        "帮我在安卓那个看天气的软件里查一下北京",
        chat=chat,
        allow_llm=True,
    )
    assert hints.platform == "android"
    assert hints.app_name == "天气助手"
    assert hints.input_texts == ("北京",)
    assert "nl:llm" in notes


def test_llm_failure_falls_back_to_regex(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    monkeypatch.setattr(
        "autopilot.authoring.nl_bootstrap._nl_llm_enabled", lambda: True
    )

    def bad(_prompt: str) -> str:
        raise AuthoringError("模拟失败")

    # 故意写得含糊，逼 resolve 走 LLM，再降级到正则
    hints, notes = resolve_nl_hints(
        "帮我弄一下那个演示相关的东西，填写 alice",
        chat=bad,
        allow_llm=True,
    )
    assert any("llm_fallback" in n for n in notes)
    assert hints.input_text == "alice"



def test_extract_ignores_unknown_platform():
    hints = extract_nl_hints_via_llm(
        "x",
        chat=lambda _p: (
            '{"platform":"windows","app_name":"","package_name":"",'
            '"start_url":"","input_texts":[]}'
        ),
    )
    assert hints.platform == ""



def test_hints_sufficient_web_needs_url():
    assert not hints_sufficient(NlHints(platform="web"))
    assert hints_sufficient(NlHints(platform="web", start_url="https://a.com"))


def test_explicit_hints_http_kept():
    h = explicit_hints(platform="http", start_url="https://api.example.test")
    assert h.platform == "http"


def test_hints_sufficient_http_without_url():
    assert hints_sufficient(NlHints(platform="http"))


def test_explicit_hints_auto_platform_cleared():
    h = explicit_hints(platform="auto", package_name="com.x")
    assert h.platform == ""
    assert h.package_name == "com.x"


def test_regex_still_works_standalone():
    h = parse_nl_hints("访问 https://example.com/login")
    assert h.platform == "web"
    assert h.start_url.startswith("https://")
