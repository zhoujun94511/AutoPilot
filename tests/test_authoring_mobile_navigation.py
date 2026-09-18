from __future__ import annotations

import json

import pytest

from autopilot.authoring import agent as agent_mod
from autopilot.authoring.contract import AuthoringRequest, GeneratedStep
from autopilot.authoring.navigation import NavigationLedger, build_navigation_plan


def _step(keyword_id: str, locator: str = "", **params: str) -> GeneratedStep:
    values = dict(params)
    if locator:
        values["locator"] = locator
    return GeneratedStep(keyword_id=keyword_id, params=values)


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_four_level_navigation_commits_only_confirmed_path(platform: str) -> None:
    start = _step("mobile_app_start", packageName=f"demo.{platform}")
    ledger = NavigationLedger(build_navigation_plan("购买指定商品"), initial_steps=[start])
    ledger.begin_page("home")

    for depth in range(1, 5):
        click = _step("mobile_element_click", f"id=level-{depth}")
        ledger.stage(click, "navigate", target_locator=click.params["locator"])
        outcome = ledger.begin_page(f"level-{depth}")
        assert outcome.page_changed
        assert outcome.incident is None

    buy = _step("mobile_element_click", "id=buy")
    ledger.commit_immediate(buy, "target", target_locator="id=buy")

    assert [s.params.get("locator") for s in ledger.final_steps()[1:]] == [
        "id=level-1",
        "id=level-2",
        "id=level-3",
        "id=level-4",
        "id=buy",
    ]
    assert ledger.plan.strategies[:2] == ("search_first", "category_fallback")


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_scroll_exploration_normalizes_to_scroll_for_element(platform: str) -> None:
    start = _step("mobile_app_start", packageName=f"demo.{platform}")
    ledger = NavigationLedger(build_navigation_plan("找到商品"), initial_steps=[start])
    ledger.begin_page("list-top")
    swipe = _step("mobile_swipe_direction", direction="上", size="半屏")
    ledger.stage(swipe, "scroll")
    ledger.begin_page("list-after-scroll")

    target = _step("mobile_element_click", "id=sku")
    ledger.commit_immediate(target, "target", target_locator="id=sku")
    final = ledger.final_steps()

    assert [s.keyword_id for s in final] == [
        "mobile_app_start",
        "mobile_slip_for_element",
        "mobile_element_click",
    ]
    assert final[1].params["locator"] == "id=sku"
    assert final[1].params["times"] == "1"
    assert ledger.requires_replay


def test_backtrack_prunes_wrong_branch_and_back_action() -> None:
    start = _step("mobile_app_start", packageName="demo")
    ledger = NavigationLedger(build_navigation_plan("购买商品"), initial_steps=[start])
    ledger.begin_page("home")
    wrong = _step("mobile_element_click", "id=wrong")
    ledger.stage(wrong, "navigate", target_locator="id=wrong")
    ledger.begin_page("wrong-category")

    back = _step("mobile_presskey", oKeys="back", count="1")
    ledger.stage(back, "backtrack")
    outcome = ledger.begin_page("home")

    assert outcome.backtracked
    assert [s.params.get("locator") for s in outcome.pruned] == ["id=wrong"]
    assert ledger.final_steps() == [start]
    assert ledger.requires_replay


def test_unchanged_page_and_budgets_create_structured_incidents() -> None:
    ledger = NavigationLedger(
        build_navigation_plan("查找", max_depth=2, max_scrolls=1),
    )
    ledger.begin_page("home")
    click = _step("mobile_element_click", "id=dead")
    ledger.stage(click, "navigate", target_locator="id=dead")
    unchanged = ledger.begin_page("home")
    assert unchanged.incident is not None
    assert unchanged.incident.kind == "navigation_unchanged"
    assert click not in ledger.final_steps()

    for before, after in (("home", "scroll-1"), ("scroll-1", "scroll-2")):
        swipe = _step("mobile_swipe_direction", direction="上")
        assert ledger.current_page_sig == before
        ledger.stage(swipe, "scroll")
        result = ledger.begin_page(after)
    assert result.incident is not None
    assert result.incident.kind == "scroll_budget"
    assert ledger.stop_reason == "scroll_budget"


def test_invalid_observation_does_not_settle_pending_transition() -> None:
    ledger = NavigationLedger(build_navigation_plan("打开详情"))
    ledger.begin_page("home")
    click = _step("mobile_element_click", "id=detail")
    ledger.stage(click, "navigate", target_locator="id=detail")

    first = ledger.begin_page(
        "empty",
        valid=False,
        error="Appium page_source 暂时不可用",
    )
    assert not first.observation_valid
    assert first.incident is not None
    assert first.incident.kind == "perception_error"
    assert ledger.pending is not None
    assert click not in ledger.final_steps()

    ledger.begin_page("empty", valid=False, error="仍未恢复")
    assert ledger.pending is not None
    assert ledger.stop_reason == "perception_unavailable"


def test_mixed_scrolls_are_not_unsafely_normalized() -> None:
    ledger = NavigationLedger(build_navigation_plan("查找商品"))
    ledger.begin_page("list")
    ledger.stage(
        _step("mobile_swipe_direction", direction="上", size="半屏"),
        "scroll",
    )
    ledger.begin_page("list-up")
    ledger.stage(
        _step("mobile_swipe_direction", direction="下", size="全屏"),
        "scroll",
    )
    ledger.begin_page("list-down")
    ledger.commit_immediate(
        _step("mobile_element_click", "id=sku"),
        "target",
        target_locator="id=sku",
    )

    assert [step.keyword_id for step in ledger.final_steps()] == [
        "mobile_swipe_direction",
        "mobile_swipe_direction",
        "mobile_element_click",
    ]
    assert not ledger.requires_replay


def test_incident_closure_is_reported_once_and_strategy_advances() -> None:
    ledger = NavigationLedger(build_navigation_plan("打开详情"))
    ledger.begin_page("home")
    click = _step("mobile_element_click", "id=missing")
    ledger.stage(click, "navigate", target_locator="id=missing")
    ledger.begin_page("home")
    assert ledger.plan.active_strategy == "category_fallback"

    target = _step("mobile_element_click", "id=alternate")
    ledger.commit_immediate(target, "target", target_locator="id=alternate")
    first_context = json.loads(ledger.prompt_context())
    second_context = json.loads(ledger.prompt_context())
    assert first_context["last_closed_incident"]["kind"] == "navigation_unchanged"
    assert second_context["last_closed_incident"] is None


def test_model_cannot_skip_navigation_strategy_without_incident() -> None:
    ledger = NavigationLedger(build_navigation_plan("购买商品"))
    assert ledger.plan.active_strategy == "search_first"
    ledger.set_strategy("target_action")
    assert ledger.plan.active_strategy == "search_first"


def test_final_steps_preserve_executed_business_repeats() -> None:
    ledger = NavigationLedger(build_navigation_plan("购买两次"))
    click = _step("mobile_element_click", "id=buy")
    ledger.commit_immediate(click, "target", target_locator="id=buy")
    ledger.commit_immediate(click, "target", target_locator="id=buy")
    assert ledger.final_steps() == [click, click]


def test_page_cycle_is_pruned_and_depth_budget_stops() -> None:
    ledger = NavigationLedger(build_navigation_plan("查找", max_depth=2))
    ledger.begin_page("a")
    to_b = _step("mobile_element_click", "id=b")
    ledger.stage(to_b, "navigate", target_locator="id=b")
    ledger.begin_page("b")
    to_a = _step("mobile_element_click", "id=a")
    ledger.stage(to_a, "navigate", target_locator="id=a")
    cycle = ledger.begin_page("a")
    assert cycle.backtracked
    assert ledger.final_steps() == []
    assert ledger.requires_replay

    to_b_again = _step("mobile_element_click", "id=b2")
    ledger.stage(to_b_again, "navigate", target_locator="id=b2")
    ledger.begin_page("b2")
    too_deep = _step("mobile_element_click", "id=c")
    ledger.stage(too_deep, "navigate", target_locator="id=c")
    ledger.begin_page("c")
    over_limit = _step("mobile_element_click", "id=d")
    ledger.stage(over_limit, "navigate", target_locator="id=d")
    outcome = ledger.begin_page("d")
    assert outcome.incident is not None
    assert outcome.incident.kind == "depth_budget"
    assert ledger.stop_reason == "depth_budget"


def test_backtrack_budget_stops_repeated_wrong_branches() -> None:
    ledger = NavigationLedger(build_navigation_plan("查找", max_backtracks=1))
    ledger.begin_page("home")
    for branch in ("wrong-1", "wrong-2"):
        click = _step("mobile_element_click", f"id={branch}")
        ledger.stage(click, "navigate", target_locator=f"id={branch}")
        ledger.begin_page(branch)
        ledger.stage(_step("mobile_presskey", oKeys="back"), "backtrack")
        outcome = ledger.begin_page("home")
    assert outcome.incident is not None
    assert outcome.incident.kind == "backtrack_budget"
    assert ledger.stop_reason == "backtrack_budget"


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_agent_prunes_wrong_branch_and_replays_clean_path(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    state = {"page": "home", "buy_count": 0}
    pages = {
        "home": [{"l": "id=wrong"}, {"l": "id=right"}],
        "wrong": [],
        "detail": [{"l": "id=buy"}],
        "purchased": [{"l": "id=order-success", "tx": "购买成功"}],
    }

    def capture(_ctx: object, _platform: str) -> dict[str, object]:
        elements = pages[state["page"]]
        return {
            "elements_text": json.dumps(elements),
            "element_count": len(elements),
            "screen": "",
        }

    monkeypatch.setattr(agent_mod, "capture_settled_ui_context", capture)
    monkeypatch.setattr(agent_mod, "capture_ui_context", capture)
    monkeypatch.setattr(
        agent_mod,
        "resolve_planned_locators",
        lambda steps, *_args, **_kwargs: (steps, []),
    )

    def execute(step: GeneratedStep, _ctx: object) -> None:
        kid = step.keyword_id
        locator = step.params.get("locator")
        if kid == "mobile_app_start":
            state["page"] = "home"
        elif kid == "mobile_presskey":
            state["page"] = "home"
        elif locator == "id=wrong":
            state["page"] = "wrong"
        elif locator == "id=right":
            state["page"] = "detail"
        elif locator == "id=buy":
            state["buy_count"] += 1
            state["page"] = "purchased"

    responses = iter([
        {
            "done": False,
            "steps": [{
                "keyword_id": "mobile_element_click",
                "params": {"locator": "id=wrong"},
                "action_role": "navigate",
            }],
        },
        {
            "done": False,
            "steps": [{
                "keyword_id": "mobile_presskey",
                "params": {"oKeys": "back", "count": "1"},
                "action_role": "backtrack",
            }],
        },
        {
            "done": False,
            "steps": [{
                "keyword_id": "mobile_element_click",
                "params": {"locator": "id=right"},
                "action_role": "navigate",
            }],
        },
        {
            "done": True,
            "title": "购买商品",
            "steps": [{
                "keyword_id": "mobile_element_click",
                "params": {"locator": "id=buy"},
                "action_role": "target",
            }],
        },
    ])

    draft = agent_mod.run_session_authoring(
        AuthoringRequest(
            natural_language="购买商品",
            platform=platform,
            package_name="demo.shop",
            max_steps=12,
            max_turns=8,
        ),
        ctx=object(),
        chat=lambda _prompt: json.dumps(next(responses), ensure_ascii=False),
        executor=execute,
    )

    locators = [s.params.get("locator") for s in draft.steps]
    assert "id=wrong" not in locators
    assert [value for value in locators if value] == ["id=right", "id=buy"]
    assert not any(s.keyword_id == "mobile_presskey" for s in draft.steps)
    assert draft.session_verified
    assert draft.goal_completed
    assert state["buy_count"] == 1
    assert draft.decision_trace["replay"]["passed"] is True
    assert all(
        row["passed"]
        for row in draft.decision_trace["replay"]["checkpoints"]
    )
    assert any(
        turn["navigation"].get("terminal_post_observe", {}).get("passed")
        for turn in draft.decision_trace["turns"]
    )


def test_use_current_app_cannot_verify_rewritten_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"page": "top", "buy_count": 0}

    def capture(_ctx: object, _platform: str) -> dict[str, object]:
        items = [] if state["page"] == "top" else [{"l": "id=buy"}]
        return {
            "elements_text": json.dumps(items),
            "element_count": len(items),
            "screen": "",
        }

    monkeypatch.setattr(agent_mod, "capture_settled_ui_context", capture)
    monkeypatch.setattr(agent_mod, "capture_ui_context", capture)
    monkeypatch.setattr(
        agent_mod,
        "resolve_planned_locators",
        lambda steps, *_args, **_kwargs: (steps, []),
    )

    def execute(step: GeneratedStep, _ctx: object) -> None:
        if step.keyword_id == "mobile_swipe_direction":
            state["page"] = "scrolled"
        elif step.params.get("locator") == "id=buy":
            state["buy_count"] += 1

    responses = iter([
        {
            "done": False,
            "steps": [{
                "keyword_id": "mobile_swipe_direction",
                "params": {"direction": "上", "size": "半屏"},
                "action_role": "scroll",
            }],
        },
        {
            "done": True,
            "steps": [{
                "keyword_id": "mobile_element_click",
                "params": {"locator": "id=buy"},
                "action_role": "target",
            }],
        },
    ])
    draft = agent_mod.run_session_authoring(
        AuthoringRequest(
            natural_language="购买商品",
            platform="android",
            use_current_app=True,
            max_steps=6,
            max_turns=4,
        ),
        ctx=object(),
        chat=lambda _prompt: json.dumps(next(responses), ensure_ascii=False),
        executor=execute,
    )

    assert [s.keyword_id for s in draft.steps] == ["mobile_slip_for_element"]
    assert not draft.goal_completed
    assert not draft.session_verified
    assert state["buy_count"] == 0
    assert draft.decision_trace["replay"]["passed"] is False
