"""审计对齐：完成门禁、口令遮罩、定位分差、HTTP 断言、采页保真。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

# noinspection PyProtectedMember
from autopilot.authoring.agent import _observe_terminal_target, run_session_authoring
# noinspection PyProtectedMember
from autopilot.authoring.capture import _element_priority, _trim_elements_for_budget
from autopilot.authoring.contract import AuthoringRequest, GeneratedStep
from autopilot.authoring.gate import assert_local_dry_run_passed
from autopilot.authoring.goal_judge import completion_evidence, heuristic_goal_judge
from autopilot.authoring.locate_resolve import match_hint_to_locator, parse_page_elements
from autopilot.authoring.pipeline import generate_traditional_case
from autopilot.authoring.secrets import (
    SECRET_PLACEHOLDER_PREFIX,
    collect_secret_map,
    mask_text,
    restore_secrets,
    restore_step_params,
)
from autopilot.authoring.step_runner import execute_keyword_step
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.registry import KeywordDef, REGISTRY


def test_gate_defaults_goal_completed_false(tmp_path: Path):
    path = tmp_path / "a.tc.yaml"
    path.write_text("type: testcase\n", encoding="utf-8")
    gate = assert_local_dry_run_passed(path, session_verified=True)
    assert gate.allow_upload is False
    assert "goal_incomplete" in gate.details


def test_completion_evidence_rejects_model_done_alone():
    recorded = [GeneratedStep(keyword_id="mobile_element_click", comment="点")]
    ok, reason = completion_evidence(
        recorded,
        platform="ios",
        natural_language="打开蓝牙",
        model_done=True,
        target_confirmed=False,
    )
    assert ok is False
    assert "缺少" in reason


def test_completion_evidence_accepts_assert_or_confirmed_target():
    asserted = [GeneratedStep(keyword_id="mobile_verify_element_visible")]
    ok, _reason = completion_evidence(
        asserted,
        platform="ios",
        natural_language="打开蓝牙并验证可见",
        model_done=True,
        target_confirmed=False,
    )
    assert ok is True

    clicked = [GeneratedStep(keyword_id="mobile_element_click")]
    ok, _reason = completion_evidence(
        clicked,
        platform="ios",
        natural_language="打开蓝牙",
        model_done=True,
        target_confirmed=True,
    )
    assert ok is True


def test_http_requires_assert_even_with_target_confirmed():
    recorded = [GeneratedStep(keyword_id="http_get", params={"url": "https://x.test"})]
    ok, reason = completion_evidence(
        recorded,
        platform="http",
        natural_language="调用接口",
        model_done=True,
        target_confirmed=True,
    )
    assert ok is False
    assert "HTTP" in reason
    assert "断言" in reason

    with_assert = recorded + [
        GeneratedStep(keyword_id="http_assert_status", params={"expected": "200"})
    ]
    ok, _reason = completion_evidence(
        with_assert,
        platform="http",
        natural_language="调用接口并确认状态码",
        model_done=True,
        target_confirmed=False,
    )
    assert ok is True


def test_nl_verify_language_requires_verify_step():
    recorded = [GeneratedStep(keyword_id="mobile_element_click")]
    ok, reason = completion_evidence(
        recorded,
        platform="ios",
        natural_language="打开蓝牙并确认已开启",
        model_done=True,
        target_confirmed=True,
    )
    assert ok is False
    assert "verify_" in reason


def test_heuristic_judge_false_without_evidence():
    note = heuristic_goal_judge(
        goal_completed=True,
        recorded=[GeneratedStep(keyword_id="mobile_element_click")],
        warnings=[],
        platform="ios",
        natural_language="打开蓝牙",
        target_confirmed=False,
    )
    assert note["passed"] is False


def test_heuristic_judge_passes_with_assert():
    note = heuristic_goal_judge(
        goal_completed=True,
        recorded=[GeneratedStep(keyword_id="mobile_verify_text", comment="校验")],
        warnings=[],
        platform="ios",
        natural_language="打开蓝牙并验证文案",
        target_confirmed=False,
    )
    assert note["passed"] is True


def test_match_hint_rejects_short_substring_and_ties():
    elements = parse_page_elements(
        json.dumps(
            [
                {"l": "name::WLAN设置", "tx": "WLAN设置"},
                {"l": "name::通用", "tx": "通用"},
            ],
            ensure_ascii=False,
        )
    )
    assert match_hint_to_locator("设置", elements) == ""

    exact = parse_page_elements(
        json.dumps(
            [
                {"l": "name::设置", "tx": "设置"},
                {"l": "name::WLAN设置", "tx": "WLAN设置"},
            ],
            ensure_ascii=False,
        )
    )
    assert match_hint_to_locator("设置", exact) == "name::设置"

    ties = parse_page_elements(
        json.dumps(
            [
                {"l": "name::登录页", "tx": "登录页"},
                {"l": "name::登录中", "tx": "登录中"},
            ],
            ensure_ascii=False,
        )
    )
    assert match_hint_to_locator("登录", ties) == ""


def test_secrets_mask_password_near_label():
    nl = "打开设置，输入密码 SuperSecret99 并登录"
    mapping = collect_secret_map(nl, ("SuperSecret99",))
    assert mapping["SuperSecret99"].startswith(SECRET_PLACEHOLDER_PREFIX)
    masked = mask_text(nl, mapping)
    assert "SuperSecret99" not in masked
    assert SECRET_PLACEHOLDER_PREFIX in masked
    assert restore_secrets(masked, mapping) == nl
    restored = restore_step_params({"text": mapping["SuperSecret99"]}, mapping)
    assert restored["text"] == "SuperSecret99"


# noinspection PyProtectedMember
def test_prefer_texts_keeps_goal_control_under_budget():
    noise = [
        {"text": f"noise-{i}", "clickable": True, "locators": [f"id::n{i}"]}
        for i in range(20)
    ]
    target = {"text": "提交订单", "clickable": True, "locators": ["name::提交订单"]}
    kept = _trim_elements_for_budget(
        noise + [target],
        max_elements=3,
        max_chars=12000,
        prefer_texts=["提交订单"],
    )
    assert any(el.get("text") == "提交订单" for el in kept)
    assert _element_priority(target, prefer_texts=["提交订单"]) > _element_priority(
        noise[0], prefer_texts=["提交订单"]
    )


def test_step_runner_writes_normalized_locator(monkeypatch):
    monkeypatch.setitem(
        REGISTRY,
        "mobile_element_click",
        KeywordDef(
            keyword_id="mobile_element_click",
            func=lambda _ctx, **_kw: None,
            name="click",
            category="test",
        ),
    )
    ctx = ExecutionContext()
    ctx.set_var("__current_platform__", "ios")
    step = GeneratedStep(
        keyword_id="mobile_element_click",
        params={"locator": "i:General"},
    )
    execute_keyword_step(step, ctx)
    assert step.params["locator"] == "name::General"


# noinspection PyProtectedMember
def test_high_stakes_target_needs_goal_token(monkeypatch):
    from autopilot.authoring import agent as ag

    monkeypatch.setattr(
        ag,
        "_call_capture",
        lambda *_a, **_k: {
            "elements_text": '[{"l":"name::ok","tx":"成功"}]',
            "element_count": 1,
            "_meta": {"settled": True, "timed_out": False},
        },
    )
    ok, reason, evidence = _observe_terminal_target(
        ctx=object(),
        platform="ios",
        expected_before_sig="before",
        natural_language="登录并购买商品",
    )
    assert ok is False
    assert "需求匹配" in reason
    assert evidence.get("semantic_hit") is False

    ok, reason, _evidence = _observe_terminal_target(
        ctx=object(),
        platform="web",
        expected_before_sig="before",
        natural_language="打开蓝牙",
    )
    assert ok is True
    assert reason == ""


def test_plan_only_prompt_masks_password(tmp_path: Path, monkeypatch):
    from autopilot.authoring import pipeline as pl

    monkeypatch.setattr(
        pl,
        "build_keyword_catalog",
        lambda _p: [{"id": "mobile_element_click", "params": []}],
    )
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda _p: frozenset({"mobile_element_click"}),
    )
    seen: list[str] = []

    def chat(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps(
            {
                "title": "登录",
                "steps": [
                    {
                        "keyword_id": "mobile_element_click",
                        "params": {"locator": "name::登录"},
                        "comment": "点登录",
                    }
                ],
                "notes": "",
            },
            ensure_ascii=False,
        )

    generate_traditional_case(
        AuthoringRequest(
            natural_language="打开设置，输入密码 SuperSecret99 并登录",
            platform="android",
            draft_only=True,
            mode="plan_only",
        ),
        elements_text='[{"tx":"登录","l":"name::登录"}]',
        project_dir=tmp_path,
        chat=chat,
        save=False,
    )
    assert seen
    assert "SuperSecret99" not in seen[0]
    assert SECRET_PLACEHOLDER_PREFIX in seen[0]


def test_session_prompt_masks_password(monkeypatch):
    from autopilot.authoring import agent as ag

    ids = ["mobile_element_text_input"]
    els = '[{"t":"TextField","l":"name::pwd","ed":1,"tx":"密码"}]'
    monkeypatch.setattr(ag, "build_keyword_catalog", lambda _p: [{"id": i} for i in ids])
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda _p: set(ids),
    )
    monkeypatch.setattr(
        ag,
        "capture_ui_context",
        lambda *_a, **_k: {"element_count": 1, "elements_text": els, "screen": "1x1"},
    )
    monkeypatch.setattr(
        ag,
        "capture_settled_ui_context",
        lambda *_a, **_k: {"element_count": 1, "elements_text": els, "screen": "1x1"},
    )
    prompts: list[str] = []

    def chat(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "done": True,
                "title": "登录",
                "steps": [
                    {
                        "keyword_id": "mobile_element_text_input",
                        "params": {"locator": "name::pwd", "text": "__AP_SECRET_1__"},
                        "action_role": "target",
                    }
                ],
            },
            ensure_ascii=False,
        )

    executed: list[GeneratedStep] = []

    def executor(step: GeneratedStep, _ctx) -> None:
        executed.append(step)

    run_session_authoring(
        AuthoringRequest(
            natural_language="输入密码 SuperSecret99 并登录",
            platform="ios",
            mode="session",
            input_texts=("SuperSecret99",),
        ),
        ctx=ExecutionContext(),
        chat=chat,
        executor=executor,
    )
    assert prompts
    assert all("SuperSecret99" not in p for p in prompts)
    assert any(SECRET_PLACEHOLDER_PREFIX in p for p in prompts)
    assert executed
    assert executed[0].params.get("text") == "SuperSecret99"


def test_llm_goal_judge_masks_secret_in_prompt(monkeypatch):
    from autopilot.authoring import goal_judge as gj

    monkeypatch.setenv("AUTOPILOT_AUTHORING_GOAL_JUDGE", "llm")
    seen: list[str] = []

    def chat(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps(
            {"passed": False, "reason": "未覆盖", "confidence": 0.4},
            ensure_ascii=False,
        )

    out = gj.maybe_llm_goal_judge(
        natural_language="输入密码 SuperSecret99 登录",
        recorded=[
            GeneratedStep(
                keyword_id="mobile_element_text_input",
                params={"text": "SuperSecret99"},
            )
        ],
        goal_completed=False,
        warnings=[],
        chat=chat,
        platform="ios",
    )
    assert out is not None
    assert seen
    assert "SuperSecret99" not in seen[0]
    assert SECRET_PLACEHOLDER_PREFIX in seen[0]


def test_dialog_goal_completed_getattr_defaults_false():
    draft = SimpleNamespace(session_verified=True)
    assert bool(getattr(draft, "goal_completed", False)) is False
