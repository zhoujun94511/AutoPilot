"""编写会话：同一定位 + 页面未变 → 重复操作升级 / 熔断。"""

from __future__ import annotations

import json
from pathlib import Path

from autopilot.authoring.contract import AuthoringRequest, GeneratedStep
from autopilot.authoring.goal_judge import heuristic_goal_judge, judge_authoring_goal
from autopilot.authoring.pipeline import generate_traditional_case
from autopilot.authoring.repeat import (
    LEVEL_STOP,
    REPEAT_FAILED,
    RepeatWatch,
    action_fingerprint,
    assess_repeat,
)


class _Ctx:
    @staticmethod
    def resolve(value: str) -> str:
        return value


def test_same_fingerprint_escalates_to_stop():
    fp = action_fingerprint("mobile_element_click", "name::ok", page_sig="p1")
    recent = [fp] * 6
    v = assess_repeat(recent)
    assert v.should_stop
    assert v.level == LEVEL_STOP
    assert v.message == REPEAT_FAILED


def test_stuck_retry_escalates_then_new_page_is_clean():
    watch = RepeatWatch()
    watch.record_executed(
        "mobile_element_click", "name::ok", "page-a", page_changing=True
    )
    assert watch.page_stuck("page-a")
    assert not watch.page_stuck("page-b")
    v = None
    for _ in range(5):
        v = watch.note_stuck_retry("mobile_element_click", "name::ok", "page-a")
    assert v is not None and v.should_stop
    watch2 = RepeatWatch()
    watch2.record_executed(
        "mobile_element_click", "name::ok", "page-a", page_changing=True
    )
    watch2.record_executed(
        "mobile_element_click", "name::ok", "page-b", page_changing=True
    )
    assert not watch2.page_stuck("page-a")
    assert watch2.page_stuck("page-b")


def test_wait_not_tracked():
    watch = RepeatWatch()
    assert watch.record_executed("sleep", "", "p", page_changing=False) == ""
    assert watch.note_stuck_retry("mobile_wait_element", "name::ok", "p").consecutive == 0


def test_session_same_click_stops(tmp_path: Path, monkeypatch):
    from autopilot.authoring import agent as ag
    from autopilot.authoring import codegen as cg

    ids = {"mobile_app_start", "mobile_element_click"}
    monkeypatch.setattr(cg, "allowed_keyword_ids", lambda _p: frozenset(ids))
    monkeypatch.setattr(
        ag,
        "build_keyword_catalog",
        lambda _p, **_k: [{"id": i, "params": []} for i in sorted(ids)],
    )
    page = '[{"t":"Button","tx":"提交","l":"name::submit","ck":1}]'

    def fake_capture(_ctx, platform, **_k):
        return {
            "platform": platform,
            "elements_text": page,
            "element_count": 1,
            "elements": [],
            "screen": "390x844",
        }

    monkeypatch.setattr(ag, "capture_ui_context", fake_capture)
    monkeypatch.setattr(ag, "capture_settled_ui_context", fake_capture)

    def fake_chat(_prompt: str) -> str:
        return json.dumps(
            {
                "done": False,
                "steps": [
                    {
                        "keyword_id": "mobile_element_click",
                        "params": {"locator": "name::submit"},
                        "comment": "点击提交",
                    }
                ],
            },
            ensure_ascii=False,
        )

    executed: list[GeneratedStep] = []

    def fake_exec(step: GeneratedStep, _ctx) -> None:
        executed.append(step)

    result = generate_traditional_case(
        AuthoringRequest(
            natural_language="点击提交",
            platform="ios",
            mode="session",
            package_name="com.example.demo",
            draft_only=True,
            max_turns=12,
        ),
        ctx=_Ctx(),
        chat=fake_chat,
        executor=fake_exec,
        project_dir=tmp_path,
        save=False,
    )
    clicks = [s for s in executed if s.keyword_id == "mobile_element_click"]
    assert len(clicks) == 1
    assert any("未变化的页面" in w or "重复操作" in w for w in result.draft.warnings)
    assert result.draft.goal_completed is False


def test_heuristic_judge_does_not_flip_completed():
    recorded = [GeneratedStep(keyword_id="mobile_element_click", comment="点")]
    note = heuristic_goal_judge(
        goal_completed=True,
        recorded=recorded,
        warnings=["同一操作在未变化的页面上连续 6 次，停止编写"],
    )
    assert note["passed"] is True
    assert note["source"] == "heuristic"


def test_judge_off_returns_empty(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_GOAL_JUDGE", "off")
    out = judge_authoring_goal(
        natural_language="点提交",
        recorded=[],
        goal_completed=False,
        warnings=[],
        chat=lambda _p: "{}",
    )
    assert out == {}
