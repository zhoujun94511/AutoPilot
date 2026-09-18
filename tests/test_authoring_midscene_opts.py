"""Midscene 对照改进白盒：定位缓存、决策轨迹、无断言软警告。"""

from __future__ import annotations

import json

from autopilot.authoring import agent as agent_mod
from autopilot.authoring.codegen import save_draft_tc
from autopilot.authoring.contract import AuthoringDraft, GeneratedStep
from autopilot.authoring.locator_cache import PageLocatorCache, page_signature
from autopilot.authoring.prompt import build_agent_turn_prompt
from autopilot.authoring.registry_catalog import build_keyword_catalog
from autopilot.authoring.turn_trace import (
    AUTHORING_TRACE_FILE,
    AuthoringTrace,
    TurnTraceRecord,
    read_authoring_trace,
    trace_path_for_case,
    write_authoring_trace,
)

_filter_planned_steps = getattr(agent_mod, "_filter_planned_steps")
_missing_assert_warning = getattr(agent_mod, "_missing_assert_warning")
_nl_wants_assert = getattr(agent_mod, "_nl_wants_assert")
_normalize_assertion_step = getattr(agent_mod, "_normalize_assertion_step")
_preflight_locator_step = getattr(agent_mod, "_preflight_locator_step")


def test_page_signature_order_independent():
    a = '[{"l":"id::a"},{"l":"name::b"}]'
    b = '[{"l":"name::b"},{"l":"id::a"}]'
    assert page_signature(a) == page_signature(b)
    assert page_signature(a) != page_signature('[{"l":"id::c"}]')


def test_page_signature_distinguishes_same_locator_with_changed_semantics():
    before = '[{"l":"id::row","tx":"商品 A","p":"0,100,100,40"}]'
    after = '[{"l":"id::row","tx":"商品 B","p":"0,160,100,40"}]'
    assert page_signature(before) != page_signature(after)


def test_mobile_locator_safety_net_uses_fresh_live_tree(monkeypatch):
    monkeypatch.setattr(
        agent_mod,
        "capture_ui_context",
        lambda _ctx, _platform: {
            "elements_text": '[{"l":"id::new","tx":"新页面"}]'
        },
    )
    ok, reason, live_sig = _preflight_locator_step(
        GeneratedStep("mobile_element_click", {"locator": "id::old"}),
        ctx=object(),
        platform="android",
        expected_page_sig="old-signature",
    )
    assert ok is False
    assert "page_drift" in reason
    assert live_sig != "old-signature"


def test_mobile_locator_safety_net_rejects_ambiguous_live_locator(monkeypatch):
    page = (
        '[{"l":"id::android:id/title","tx":"Wi-Fi","dup":2},'
        '{"l":"id::android:id/title","tx":"About phone","dup":2}]'
    )
    monkeypatch.setattr(
        agent_mod,
        "capture_ui_context",
        lambda _ctx, _platform: {"elements_text": page},
    )
    ok, reason, _live_sig = _preflight_locator_step(
        GeneratedStep(
            "mobile_element_click",
            {"locator": "id::android:id/title"},
        ),
        ctx=object(),
        platform="android",
        expected_page_sig=page_signature(page),
    )

    assert ok is False
    assert "locator_ambiguous" in reason


def test_filter_skips_overlay_app_start():
    start = GeneratedStep(
        "mobile_app_start",
        {"packageName": "com.android.permissioncontroller"},
    )
    click = GeneratedStep("mobile_element_click", {"locator": "id::allow"})
    kept, skipped, _notes = _filter_planned_steps(
        [start, click],
        recorded=[],
        page_locators={"id::allow"},
        target_package="com.example.app",
        current_packages=("com.android.permissioncontroller",),
    )
    assert [step.keyword_id for step in kept] == ["mobile_element_click"]
    assert any("再次启动" in note for note in skipped)


def test_filter_allows_switching_app_from_overlay():
    start = GeneratedStep(
        "mobile_app_start",
        {"packageName": "com.other.app"},
    )
    kept, skipped, _notes = _filter_planned_steps(
        [start],
        recorded=[],
        page_locators=set(),
        target_package="com.example.app",
        current_packages=("com.android.permissioncontroller",),
    )
    assert kept == [start]
    assert skipped == []


def test_filter_skips_restart_while_already_in_target():
    start = GeneratedStep(
        "mobile_app_start",
        {"packageName": "com.example.app"},
    )
    kept, skipped, _notes = _filter_planned_steps(
        [start],
        recorded=[],
        page_locators=set(),
        target_package="com.example.app",
        current_packages=("com.example.app",),
    )
    assert kept == []
    assert any("再次启动" in note for note in skipped)


def test_filter_skips_blank_app_start_on_overlay():
    start = GeneratedStep("mobile_app_start", {})
    kept, skipped, _notes = _filter_planned_steps(
        [start],
        recorded=[],
        page_locators=set(),
        target_package="com.example.app",
        current_packages=("com.android.permissioncontroller",),
    )
    assert kept == []
    assert any("再次启动" in note for note in skipped)


def test_filter_skips_duplicate_http_session_begin():
    first = GeneratedStep(
        "http_session_begin",
        {"base_url": "https://api.example.test"},
    )
    again = GeneratedStep(
        "http_session_begin",
        {"base_url": "https://api.example.test"},
    )
    kept, skipped, _notes = _filter_planned_steps(
        [again],
        recorded=[first],
        page_locators=set(),
    )
    assert kept == []
    assert any("重复入口" in note for note in skipped)


def test_filter_keeps_first_app_start_when_page_empty():
    start = GeneratedStep(
        "mobile_app_start",
        {"packageName": "com.example.app"},
    )
    kept, skipped, _notes = _filter_planned_steps(
        [start],
        recorded=[],
        page_locators=set(),
        target_package="com.example.app",
        current_packages=(),
    )
    assert kept == [start]
    assert skipped == []


def test_filter_preserves_explicit_business_repeat():
    click = GeneratedStep("mobile_element_click", {"locator": "id::buy"})
    kept, skipped, _notes = _filter_planned_steps(
        [click, click],
        recorded=[],
        page_locators={"id::buy"},
        natural_language="购买两次",
    )
    assert kept == [click, click]
    assert skipped == []


def test_mobile_navigation_keywords_are_pinned_in_small_catalog():
    expected = {
        "mobile_presskey",
        "mobile_swipe_direction",
        "mobile_slip_for_element",
        "mobile_element_text_clear",
        "mobile_wait_element_visible",
        "mobile_verify_element_existed",
        "mobile_verify_element_visible",
        "mobile_verify_element_text",
    }
    for platform in ("android", "ios"):
        ids = {
            item["id"]
            for item in build_keyword_catalog(platform, max_items=12)
        }
        assert expected <= ids


def test_assert_role_promotes_mobile_visibility_wait_to_verify():
    step = GeneratedStep(
        "mobile_wait_element_visible",
        {"locator": "name::General", "isVisible": "true"},
    )

    note = _normalize_assertion_step(
        step,
        role="assert",
        assertion_requested=True,
    )

    assert step.keyword_id == "mobile_verify_element_visible"
    assert "断言规范化" in note
    assert _missing_assert_warning([step], "验证 General 页面已打开") == ""


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
    http_get = [GeneratedStep(keyword_id="http_get", params={"url": "/health"})]
    http_warn = _missing_assert_warning(http_get, "调用健康检查", "http")
    assert "http_assert" in http_warn
    http_ok = http_get + [
        GeneratedStep(keyword_id="http_assert_status", params={"expected": "200"})
    ]
    assert _missing_assert_warning(http_ok, "调用健康检查", "http") == ""
    assert _missing_assert_warning(http_get, "打开页面", "ios") == ""


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


def test_authoring_trace_isolated_per_case_and_reads_legacy(tmp_path):
    first = tmp_path / "first.tc.yaml"
    second = tmp_path / "second.tc.yaml"
    first.write_text("type: testcase\n", encoding="utf-8")
    second.write_text("type: testcase\n", encoding="utf-8")
    write_authoring_trace(first, {"title": "first", "turns": []})
    write_authoring_trace(second, {"title": "second", "turns": []})

    assert trace_path_for_case(first).is_file()
    assert trace_path_for_case(second).is_file()
    assert read_authoring_trace(first)["title"] == "first"
    assert read_authoring_trace(second)["title"] == "second"


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
