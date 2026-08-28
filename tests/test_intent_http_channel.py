"""C1：Intent channel=ui|http|auto → HTTP 关键字。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autopilot.intent.bindings import load_binding, upsert_step_binding
from autopilot.intent.heal_attr import classify_intent_failure
from autopilot.intent import resolve as resolve_mod
from autopilot.intent.resolve import effective_channel, resolve_candidates
from autopilot.intent.runtime import IntentRuntime
from autopilot.keywords.registry import KeywordError
from autopilot.mgmt import logical_import as logical_import_mod

_http_candidates = getattr(resolve_mod, "_http_candidates")
_intent_step_nodes = getattr(logical_import_mod, "_intent_step_nodes")


class _Ctx:
    def __init__(self, project: Path) -> None:
        self.vars: dict = {
            "__project_path__": str(project),
            "__run_platform__": "web",
            "__logical_case_id__": "lc-http",
        }
        self.calls: list[tuple[str, dict]] = []

    def get_var(self, name: str, default=None):
        return self.vars.get(name, default)

    def set_var(self, name: str, value) -> None:
        self.vars[name] = value

    @staticmethod
    def resolve(v: str) -> str:
        return v


def test_default_channel_stays_ui(tmp_path, monkeypatch):
    seen: list[str] = []

    def fake_resolve(**kwargs):
        seen.append(str(kwargs.get("channel") or "ui"))
        return [
            {
                "keyword_id": "web_element_click",
                "locator": "xpath:://*[@id='x']",
                "params": {"locator": "xpath:://*[@id='x']"},
                "resolver": "heuristic",
                "score": 0.8,
            }
        ]

    monkeypatch.setattr("autopilot.intent.runtime.resolve_candidates", fake_resolve)
    monkeypatch.setattr("autopilot.intent.runtime.detect_platform", lambda _c: "web")
    monkeypatch.setattr(
        IntentRuntime,
        "_invoke",
        lambda _self, kid, params: None,
    )
    ctx = _Ctx(tmp_path)
    ctx.vars["__logical_case_id__"] = ""
    out = IntentRuntime(ctx).run(
        intent_id="s1",
        action="click",
        target="登录",
        logical_case_id="",
    )
    assert out.binding_hit == "resolved"
    assert seen and seen[0] == "ui"


def test_auto_picks_http_from_text():
    assert (
        effective_channel(
            "auto",
            intent_text="调用 /api/v1/orders 接口",
            action="custom",
            target="",
            value="",
        )
        == "http"
    )
    assert (
        effective_channel(
            "auto",
            intent_text="点击登录按钮",
            action="click",
            target="登录",
            value="",
        )
        == "ui"
    )


def test_auto_picks_http_from_binding_cache():
    cached = {
        "channel": "http",
        "platform": "http",
        "keyword_id": "http_get",
        "params": {"url": "/api/v1/health"},
    }
    assert effective_channel("auto", cached=cached, intent_text="随便") == "http"


def test_http_candidates_get_path():
    cands = _http_candidates(
        action="custom",
        target="",
        value="",
        text="GET /api/v1/orders 期望 status 200",
    )
    assert len(cands) == 1
    c = cands[0]
    assert c["keyword_id"] == "http_get"
    assert c["params"]["url"] == "/api/v1/orders"
    assert c["method"] == "GET"
    assert c["follow_ups"]
    assert c["follow_ups"][0]["keyword_id"] == "http_assert_status"


def test_resolve_candidates_http_channel():
    cands = resolve_candidates(
        action="custom",
        target="/api/v1/health",
        value="",
        platform="web",
        channel="http",
        text="GET /api/v1/health",
    )
    assert cands and cands[0]["keyword_id"] == "http_get"


def test_http_binding_cache_hit(tmp_path, monkeypatch):
    ctx = _Ctx(tmp_path)
    upsert_step_binding(
        tmp_path,
        "lc-http",
        "s1",
        platform="http",
        keyword_id="http_get",
        params={"url": "/api/v1/health"},
        resolver="http_heuristic",
        channel="http",
        method="GET",
        path="/api/v1/health",
        follow_ups=[
            {"keyword_id": "http_assert_status", "params": {"expected": "200-299"}}
        ],
    )

    def fake_invoke(_self, keyword_id: str, params: dict) -> None:
        ctx.calls.append((keyword_id, dict(params)))

    monkeypatch.setattr(IntentRuntime, "_invoke", fake_invoke)
    out = IntentRuntime(ctx).run(
        intent_id="s1",
        action="custom",
        text="health",
        logical_case_id="lc-http",
        channel="http",
    )
    assert out.binding_hit == "cache"
    assert out.resolve_strategy == "http_cache"
    assert out.keyword_id == "http_get"
    assert [c[0] for c in ctx.calls] == ["http_get", "http_assert_status"]
    assert out.verification_status == "passed"


def test_http_heuristic_resolve_and_upsert(tmp_path, monkeypatch):
    ctx = _Ctx(tmp_path)

    def fake_invoke(_self, keyword_id: str, params: dict) -> None:
        ctx.calls.append((keyword_id, dict(params)))

    monkeypatch.setattr(IntentRuntime, "_invoke", fake_invoke)
    out = IntentRuntime(ctx).run(
        intent_id="s1",
        action="custom",
        text="GET /api/v1/users",
        logical_case_id="lc-http",
        channel="auto",
    )
    assert out.binding_hit == "resolved"
    assert out.resolve_strategy == "http_heuristic"
    assert out.keyword_id == "http_get"
    assert ctx.calls[0] == ("http_get", {"url": "/api/v1/users"})
    doc = load_binding(tmp_path, "lc-http")
    step = doc["steps"]["s1"]
    assert step["channel"] == "http"
    assert step["platform"] == "http"
    assert step["keyword_id"] == "http_get"
    assert step["path"] == "/api/v1/users"


def test_http_channel_no_candidate_message():
    a = classify_intent_failure(
        had_candidates=False,
        message="无法解析 HTTP 意图: 随便说说",
        intent_text="随便说说",
        channel="http",
    )
    assert a["code"] == "no_candidate"
    assert "HTTP" in a["detail"]
    assert "仅支持 UI" not in a["detail"]


def test_looks_like_http_hint_mentions_channel():
    a = classify_intent_failure(
        had_candidates=False,
        message="无法解析意图: 调用订单接口",
        intent_text="调用订单接口 检查 status code",
        channel="ui",
    )
    assert a["code"] == "looks_like_http"
    assert "channel=" in a["detail"] or "HTTP Binding" in a["detail"]


def test_logical_import_writes_channel():
    nodes = _intent_step_nodes(
        [
            {
                "id": "s1",
                "action": "custom",
                "target": "/api/v1/x",
                "text": "GET /api/v1/x",
                "channel": "http",
            }
        ],
        logical_case_id="lc1",
    )
    assert nodes[0]["params"]["channel"] == "http"


def test_http_delete_blocked_by_risk(tmp_path, monkeypatch):
    ctx = _Ctx(tmp_path)
    # 不 mock _invoke，走真实 risk 门禁
    with pytest.raises(KeywordError, match="高风险|irreversible|http_delete"):
        IntentRuntime(ctx).run(
            intent_id="s1",
            action="delete",
            text="DELETE /api/v1/users/1",
            logical_case_id="lc-http",
            channel="http",
        )


def test_fixture_binding_shape():
    root = Path(__file__).resolve().parent / "fixtures" / "intent_http"
    binding = json.loads((root / "bindings" / "lc-http-demo.json").read_text(encoding="utf-8"))
    step = binding["steps"]["s1"]
    assert step["channel"] == "http"
    assert step["keyword_id"] == "http_get"
    assert step["follow_ups"]
