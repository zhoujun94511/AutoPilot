"""Web 链路 3：Selenium/Playwright 共用导航、安全网与重放语义。"""

from __future__ import annotations

import json

import pytest

from autopilot.authoring import agent as agent_mod
from autopilot.authoring.capture import capture_ui_context
from autopilot.authoring.contract import AuthoringRequest, GeneratedStep
from autopilot.authoring.locator_cache import page_signature
from autopilot.authoring.navigation import NavigationLedger, build_navigation_plan
from autopilot.authoring.prompt import build_agent_turn_prompt
from autopilot.authoring.registry_catalog import build_keyword_catalog
from autopilot.authoring.session_bootstrap import prepare_authoring_session
from autopilot.authoring.step_runner import execute_keyword_step
from autopilot.keywords.context import ExecutionContext
from tests.web_live_support import page_events


WEB_IDS = {
    "web_browser_open",
    "web_browser_back",
    "web_browser_scroll_vertical_bar",
    "web_element_click",
}


def _patch_agent_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_mod,
        "build_keyword_catalog",
        lambda _platform: [{"id": kid} for kid in sorted(WEB_IDS)],
    )
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda _platform: WEB_IDS,
    )
    monkeypatch.setattr(
        agent_mod,
        "resolve_planned_locators",
        lambda steps, *_args, **_kwargs: (steps, []),
    )


@pytest.mark.parametrize("engine", ["selenium", "playwright"])
def test_web_agent_prunes_wrong_branch_and_replays_by_page_signature(
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
) -> None:
    _patch_agent_catalog(monkeypatch)
    state = {"page": "home", "submit_count": 0}
    pages = {
        "home": [{"l": "css::#wrong"}, {"l": "css::#right"}],
        "wrong": [{"l": "css::#dead-end"}],
        "detail": [{"l": "css::#submit"}],
        "success": [{"l": "css::#success", "tx": "提交成功"}],
    }

    def capture(capture_ctx: ExecutionContext, platform: str) -> dict[str, object]:
        assert platform == "web"
        assert capture_ctx.get_var("__web_engine__") == engine
        elements = pages[state["page"]]
        return {
            "elements_text": json.dumps(elements),
            "element_count": len(elements),
        }

    monkeypatch.setattr(agent_mod, "capture_settled_ui_context", capture)
    monkeypatch.setattr(agent_mod, "capture_ui_context", capture)

    def execute(step: GeneratedStep, _ctx: ExecutionContext) -> None:
        locator = step.params.get("locator")
        if step.keyword_id == "web_browser_open":
            state["page"] = "home"
        elif step.keyword_id == "web_browser_back":
            state["page"] = "home"
        elif locator == "css::#wrong":
            state["page"] = "wrong"
        elif locator == "css::#right":
            state["page"] = "detail"
        elif locator == "css::#submit":
            state["submit_count"] += 1
            state["page"] = "success"

    responses = iter([
        {
            "done": False,
            "steps": [{
                "keyword_id": "web_element_click",
                "params": {"locator": "css::#wrong"},
                "action_role": "navigate",
            }],
        },
        {
            "done": False,
            "steps": [{
                "keyword_id": "web_browser_back",
                "params": {},
                "action_role": "backtrack",
            }],
        },
        {
            "done": False,
            "steps": [{
                "keyword_id": "web_element_click",
                "params": {"locator": "css::#right"},
                "action_role": "navigate",
            }],
        },
        {
            "done": True,
            "steps": [{
                "keyword_id": "web_element_click",
                "params": {"locator": "css::#submit"},
                "action_role": "target",
            }],
        },
    ])
    ctx = ExecutionContext()
    ctx.set_var("__web_engine__", engine)
    draft = agent_mod.run_session_authoring(
        AuthoringRequest(
            natural_language="进入详情并提交",
            platform="web",
            start_url="https://example.test/",
            max_turns=8,
        ),
        ctx=ctx,
        chat=lambda _prompt: json.dumps(next(responses), ensure_ascii=False),
        executor=execute,
    )

    assert [step.keyword_id for step in draft.steps] == [
        "web_browser_open",
        "web_element_click",
        "web_element_click",
    ]
    assert [step.params.get("locator") for step in draft.steps[1:]] == [
        "css::#right",
        "css::#submit",
    ]
    assert state["submit_count"] == 1
    assert draft.session_verified
    assert draft.goal_completed
    assert draft.decision_trace["replay"]["passed"]
    assert all(
        row["passed"] for row in draft.decision_trace["replay"]["checkpoints"]
    )


def test_web_target_without_semantic_change_is_not_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_agent_catalog(monkeypatch)
    elements_text = '[{"l":"css::#submit","tx":"提交"}]'
    capture = lambda *_args, **_kwargs: {  # noqa: E731
        "elements_text": elements_text,
        "element_count": 1,
    }
    monkeypatch.setattr(agent_mod, "capture_settled_ui_context", capture)
    monkeypatch.setattr(agent_mod, "capture_ui_context", capture)
    payload = {
        "done": True,
        "steps": [{
            "keyword_id": "web_element_click",
            "params": {"locator": "css::#submit"},
            "action_role": "target",
        }],
    }
    draft = agent_mod.run_session_authoring(
        AuthoringRequest(
            natural_language="提交",
            platform="web",
            start_url="https://example.test/",
        ),
        ctx=ExecutionContext(),
        chat=lambda _prompt: json.dumps(payload, ensure_ascii=False),
        executor=lambda _step, _ctx: None,
    )
    assert not draft.session_verified
    assert not draft.goal_completed
    assert draft.decision_trace["stop_reason"] == "target_post_observe_failed"


def test_web_preflight_reports_page_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    before = '[{"l":"css::#submit","tx":"旧页面"}]'
    after = '[{"l":"css::#submit","tx":"新页面"}]'
    monkeypatch.setattr(
        agent_mod,
        "capture_ui_context",
        lambda *_args: {"elements_text": after},
    )
    ok, reason, live_sig = agent_mod._preflight_locator_step(
        GeneratedStep("web_element_click", {"locator": "css::#submit"}),
        ctx=ExecutionContext(),
        platform="web",
        expected_page_sig=page_signature(before),
    )
    assert not ok
    assert "page_drift" in reason
    assert live_sig == page_signature(after)


def test_web_scroll_is_preserved_without_mobile_normalization() -> None:
    ledger = NavigationLedger(build_navigation_plan("找到目标", platform="web"))
    ledger.begin_page("home")
    scroll = GeneratedStep(
        "web_browser_scroll_vertical_bar",
        {"height": "600"},
    )
    ledger.stage(scroll, "scroll")
    ledger.begin_page("scrolled")
    target = GeneratedStep("web_element_click", {"locator": "css::#target"})
    ledger.commit_immediate(target, "target", target_locator="css::#target")
    assert ledger.final_steps() == [scroll, target]
    assert not any(
        step.keyword_id == "mobile_slip_for_element"
        for step in ledger.final_steps()
    )


@pytest.mark.parametrize("engine", ["selenium", "playwright"])
def test_web_bootstrap_injects_engine_browser_and_does_not_reuse(
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
) -> None:
    monkeypatch.setattr("autopilot.runtime.settings.web_engine", lambda: engine)
    monkeypatch.setattr("autopilot.runtime.settings.web_browser", lambda: "headless")
    existing = ExecutionContext()
    existing.web = object()
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="打开网页",
            platform="web",
            start_url="https://example.test/",
        ),
        existing_ctx=existing,
        allow_nl_llm=False,
    )
    assert boot.ctx is not existing
    assert boot.reused_ctx is False
    assert boot.ctx.get_var("__web_engine__") == engine
    assert boot.ctx.get_var("__web_browser__") == "headless"
    assert boot.ctx.get_var("__current_platform__") == "web"


def test_web_prompt_and_small_catalog_are_web_specific() -> None:
    ids = {
        item["id"] for item in build_keyword_catalog("web", max_items=10)
    }
    assert {
        "web_browser_open",
        "web_browser_back",
        "web_browser_scroll_vertical_bar",
        "web_element_click",
    } <= ids
    prompt = build_agent_turn_prompt(
        natural_language="寻找并提交",
        platform="web",
        elements_text="[]",
        keyword_catalog=[{"id": "web_browser_back"}],
        history=[],
        navigation_context='{"active_strategy":"search_first"}',
    )
    assert "web_browser_back" in prompt
    assert "web_browser_scroll_vertical_bar" in prompt
    assert "mobile_presskey" not in prompt
    assert "mobile_swipe_direction" not in prompt


def test_live_web_authoring_capture_and_step_runner(live_ctx, engine) -> None:
    live_ctx.set_var("__current_platform__", "web")
    cap = capture_ui_context(live_ctx, "web")
    elements = json.loads(str(cap["elements_text"]))
    assert cap["element_count"] > 0
    assert any(item.get("l") for item in elements)
    execute_keyword_step(
        GeneratedStep(
            "web_element_click",
            {"locator": "id::btn", "isScroll": "否"},
        ),
        live_ctx,
    )
    assert page_events(live_ctx).get("click") == 1
    assert live_ctx.get_var("__web_engine__") == engine
