"""Midscene 对照改进白盒：定位缓存、决策轨迹、无断言软警告。"""

from __future__ import annotations

import json

from autopilot.authoring import agent as agent_mod
from autopilot.authoring.codegen import save_draft_tc
from autopilot.authoring.contract import AuthoringDraft, GeneratedStep
from autopilot.authoring.locator_cache import PageLocatorCache, page_signature
from autopilot.authoring.prompt import build_agent_turn_prompt
from autopilot.authoring.turn_trace import (
    AUTHORING_TRACE_FILE,
    AuthoringTrace,
    TurnTraceRecord,
    read_authoring_trace,
    write_authoring_trace,
)

_filter_planned_steps = getattr(agent_mod, "_filter_planned_steps")
_missing_assert_warning = getattr(agent_mod, "_missing_assert_warning")
_nl_wants_assert = getattr(agent_mod, "_nl_wants_assert")


def test_page_signature_order_independent():
    a = '[{"l":"id::a"},{"l":"name::b"}]'
    b = '[{"l":"name::b"},{"l":"id::a"}]'
    assert page_signature(a) == page_signature(b)
    assert page_signature(a) != page_signature('[{"l":"id::c"}]')


def test_locator_cache_rewrites_stale_locator():
    els = '[{"l":"name::wifi"},{"l":"id::x"}]'
    sig = page_signature(els)
    locs = {"name::wifi", "id::x"}
    cache = PageLocatorCache()
    cache.remember(sig, hint="打开无线局域网", locator="name::wifi", page_locators=locs)

    step = GeneratedStep(
        keyword_id="mobile_element_click",
        params={"locator": "name::STALE"},
        comment="打开无线局域网",
    )
    note = cache.rewrite_step_locator(step, page_sig=sig, page_locators=locs)
    assert "定位缓存" in note
    assert step.params["locator"] == "name::wifi"


def test_filter_uses_locator_cache_before_reject():
    els = '[{"l":"name::ok"}]'
    sig = page_signature(els)
    locs = {"name::ok"}
    cache = PageLocatorCache()
    cache.remember(sig, hint="点确定", locator="name::ok", page_locators=locs)

    planned, skipped, notes = _filter_planned_steps(
        [
            GeneratedStep(
                keyword_id="mobile_element_click",
                params={"locator": "name::WRONG"},
                comment="点确定",
            )
        ],
        recorded=[],
        page_locators=locs,
        locator_cache=cache,
        page_sig=sig,
    )
    assert len(planned) == 1
    assert planned[0].params["locator"] == "name::ok"
    assert skipped == []
    assert any("定位缓存" in n for n in notes)


def test_missing_assert_warning_when_nl_asks_verify():
    assert _nl_wants_assert("打开开关并确认已开启")
    steps = [
        GeneratedStep(keyword_id="mobile_element_click", params={"locator": "name::a"})
    ]
    warn = _missing_assert_warning(steps, "打开开关并确认已开启")
    assert "断言" in warn

    steps2 = steps + [
        GeneratedStep(
            keyword_id="mobile_verify_element_text",
            params={"locator": "name::a", "text": "开"},
        )
    ]
    assert _missing_assert_warning(steps2, "打开开关并确认已开启") == ""


def test_prompt_mentions_act_wait_assert():
    text = build_agent_turn_prompt(
        natural_language="打开设置",
        platform="ios",
        elements_text="[]",
        keyword_catalog=[{"id": "mobile_element_click", "params": []}],
        history=[],
    )
    assert "Act" in text and "Wait" in text and "Assert" in text
    assert "mobile_verify_" in text


def test_save_draft_writes_trace_sidecar(tmp_path):
    draft = AuthoringDraft(
        title="轨迹样例",
        platform="ios",
        steps=[
            GeneratedStep(keyword_id="mobile_app_start", params={"packageName": "x"})
        ],
        mode="session",
        goal_completed=True,
        decision_trace=AuthoringTrace(
            title="轨迹样例",
            platform="ios",
            natural_language="打开设置",
            goal_completed=True,
            turns=[
                TurnTraceRecord(
                    turn=1,
                    page_sig="abc",
                    planned=[{"keyword_id": "mobile_app_start"}],
                    executed=[{"keyword_id": "mobile_app_start"}],
                )
            ],
        ).to_dict(),
    )
    path = save_draft_tc(draft, tmp_path)
    assert path.is_file()
    trace_path = path.parent / AUTHORING_TRACE_FILE
    assert trace_path.is_file()
    data = read_authoring_trace(path)
    assert data is not None
    assert data["case_file"] == path.name
    assert data["turns"][0]["page_sig"] == "abc"


def test_match_hint_to_locator_and_resolve():
    from autopilot.authoring.locate_resolve import (
        match_hint_to_locator,
        parse_page_elements,
        resolve_planned_locators,
    )

    els = '[{"l":"name::无线局域网","tx":"无线局域网"},{"l":"id::x","tx":"其它"}]'
    elements = parse_page_elements(els)
    assert match_hint_to_locator("无线局域网", elements) == "name::无线局域网"

    steps = [
        GeneratedStep(
            keyword_id="mobile_element_click",
            params={"locator": "name::STALE", "target": "无线局域网"},
            comment="打开无线局域网",
        )
    ]
    out, notes = resolve_planned_locators(
        steps, els, page_locators={"name::无线局域网", "id::x"}, allow_deep_think=False
    )
    assert out[0].params["locator"] == "name::无线局域网"
    assert any("定位解析" in n for n in notes)


def test_empty_page_guidance():
    from autopilot.authoring.agent import _empty_page_guidance

    assert _empty_page_guidance(0, "[]")
    assert _empty_page_guidance(3, "[]") == ""


def test_try_page_nl_limits_turns(monkeypatch):
    from autopilot.authoring import agent as ag
    from autopilot.authoring.contract import AuthoringRequest
    from autopilot.keywords.context import ExecutionContext

    seen = {}

    def fake_run(req, **_kw):
        seen["max_turns"] = req.max_turns
        seen["max_steps"] = req.max_steps
        return AuthoringDraft(
            title="t",
            platform=req.platform,
            steps=[GeneratedStep(keyword_id="mobile_element_click", params={})],
            mode="session",
            goal_completed=False,
        )

    monkeypatch.setattr(ag, "run_session_authoring", fake_run)
    draft = ag.try_page_nl(
        AuthoringRequest(natural_language="点一下", platform="ios", max_steps=20),
        ctx=ExecutionContext(),
    )
    assert seen["max_turns"] == 1
    assert seen["max_steps"] <= 4
    assert draft.mode == "try_page"
    assert any("未写入" in w for w in draft.warnings)


def test_write_authoring_trace_accepts_dict(tmp_path):
    case = tmp_path / "a.tc.yaml"
    case.write_text("type: testcase\n", encoding="utf-8")
    write_authoring_trace(case, {"title": "t", "turns": []})
    raw = json.loads((tmp_path / AUTHORING_TRACE_FILE).read_text(encoding="utf-8"))
    assert raw["title"] == "t"
    assert raw["case_file"] == "a.tc.yaml"


def test_vision_fallback_disabled_by_default(monkeypatch):
    from autopilot.authoring.vision_fallback import (
        enrich_empty_page_via_vision,
        vision_fallback_enabled,
    )

    monkeypatch.delenv("AUTOPILOT_AUTHORING_VISION_FALLBACK", raising=False)
    assert vision_fallback_enabled() is False
    text, count, notes = enrich_empty_page_via_vision(
        ctx=None, platform="ios", natural_language="打开设置"
    )
    assert text == "[]"
    assert count == 0
    assert notes == []


def test_vision_fallback_candidates_to_elements():
    from autopilot.authoring.vision_fallback import candidates_to_elements

    rows = [
        {
            "keyword_id": "mobile_element_click",
            "target": "无线局域网",
            "params": {"locator": "name::无线局域网"},
        },
        {
            "keyword_id": "mobile_text_input",
            "params": {"locator": "name::搜索", "text": "x"},
            "label": "搜索",
        },
        {"keyword_id": "mobile_element_click", "params": {"locator": "name::无线局域网"}},
    ]
    els = candidates_to_elements(rows)
    assert len(els) == 2
    assert els[0]["l"] == "name::无线局域网"
    assert els[0]["tx"] == "无线局域网"
    assert els[0].get("ck") == 1
    assert els[1]["ed"] == 1


def test_model_for_purpose_env(monkeypatch):
    from autopilot.authoring.llm_client import model_for_purpose, normalize_llm_purpose

    monkeypatch.setenv("AP_AI_MODEL", "default-m")
    monkeypatch.delenv("AP_AI_PLANNING_MODEL", raising=False)
    monkeypatch.delenv("AP_AI_LOCATE_MODEL", raising=False)
    monkeypatch.delenv("AUTOPILOT_VISION_MODEL", raising=False)
    assert normalize_llm_purpose("deep_think") == "locate"
    assert model_for_purpose("authoring") == "default-m"
    monkeypatch.setenv("AP_AI_PLANNING_MODEL", "plan-m")
    assert model_for_purpose("authoring") == "plan-m"
    assert model_for_purpose("locate") == "plan-m"
    monkeypatch.setenv("AP_AI_LOCATE_MODEL", "locate-m")
    assert model_for_purpose("locate") == "locate-m"
    assert model_for_purpose("planning") == "plan-m"
