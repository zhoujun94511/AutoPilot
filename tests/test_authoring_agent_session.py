"""链路 3 会话驱动 Agent：通用场景验收（假会话 + 假 LLM）。

不绑定具体商业 App。覆盖：表单输入、改页后重观察、截图意图、定位契约。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autopilot.authoring.contract import AuthoringError, AuthoringRequest, GeneratedStep
from autopilot.authoring.pipeline import generate_traditional_case


def _patch_captures(monkeypatch, elements_text: str) -> None:
    """首回合走 settled，后续走即时采页；两者都要 mock，否则会打到真机。"""
    from autopilot.authoring import agent as ag

    def fake_capture(_ctx, platform, **_k):
        return {
            "platform": platform,
            "elements_text": elements_text,
            "element_count": 2,
            "elements": [],
            "screen": "390x844",
        }

    monkeypatch.setattr(ag, "capture_ui_context", fake_capture)
    monkeypatch.setattr(ag, "capture_settled_ui_context", fake_capture)


def _patch_catalog(monkeypatch, ids: set[str]) -> None:
    from autopilot.authoring import agent as ag
    from autopilot.authoring import codegen as cg

    monkeypatch.setattr(cg, "allowed_keyword_ids", lambda _p: frozenset(ids))
    monkeypatch.setattr(
        ag,
        "build_keyword_catalog",
        lambda _p, **_k: [{"id": i, "params": []} for i in sorted(ids)],
    )


class _FakeCtx:
    @staticmethod
    def resolve(value: str) -> str:
        return value


def test_session_form_input_then_submit(tmp_path: Path, monkeypatch):
    """通用表单：启动 → 输入 → 点击提交；定位必须来自摘要 ``l``。"""
    ids = {
        "mobile_app_start",
        "mobile_element_text_input",
        "mobile_element_click",
    }
    _patch_catalog(monkeypatch, ids)
    # 摘要带可执行 ``l``，验收 locator 契约（不是空 page_locators 绕过）
    page = (
        '[{"t":"TextField","tx":"账号","l":"name::account","ed":1},'
        '{"t":"Button","tx":"提交","l":"name::submit","ck":1}]'
    )
    _patch_captures(monkeypatch, page)

    turns = [
        {
            "title": "填写账号并提交",
            "done": False,
            "steps": [
                {
                    "keyword_id": "mobile_element_text_input",
                    "params": {"locator": "name::account", "text": "alice"},
                    "comment": "输入账号",
                }
            ],
        },
        {
            "title": "填写账号并提交",
            "done": True,
            "steps": [
                {
                    "keyword_id": "mobile_element_click",
                    "params": {"locator": "name::submit"},
                    "comment": "点击提交",
                }
            ],
        },
    ]
    call_i = {"n": 0}

    def fake_chat(_prompt: str) -> str:
        idx = min(call_i["n"], len(turns) - 1)
        call_i["n"] += 1
        return json.dumps(turns[idx], ensure_ascii=False)

    executed: list[GeneratedStep] = []

    def fake_exec(step: GeneratedStep, _ctx: _FakeCtx) -> None:
        executed.append(step)

    result = generate_traditional_case(
        AuthoringRequest(
            natural_language="打开演示应用，在账号栏输入 alice 并提交",
            platform="ios",
            mode="session",
            package_name="com.example.demo",
            draft_only=True,
            app_label="Demo",
        ),
        ctx=_FakeCtx(),
        chat=fake_chat,
        executor=fake_exec,
        project_dir=tmp_path,
        save=True,
    )

    kids = [s.keyword_id for s in executed]
    assert kids[0] == "mobile_app_start"
    assert "mobile_element_text_input" in kids
    assert "mobile_element_click" in kids
    typed = next(s for s in executed if s.keyword_id == "mobile_element_text_input")
    assert typed.params["text"] == "alice"
    assert typed.params["locator"] == "name::account"
    assert result.path is not None
    text = result.path.read_text(encoding="utf-8")
    assert "alice" in text
    assert "intent_act" not in text
    assert result.draft.mode == "session"
    assert call_i["n"] >= 2  # 点击改页后至少再观察一轮


def test_out_of_page_locator_rejected(monkeypatch):
    from autopilot.authoring.agent import run_session_authoring
    from autopilot.authoring.contract import AuthoringRequest
    from autopilot.keywords.context import ExecutionContext

    _patch_catalog(
        monkeypatch,
        {"mobile_element_click"},
    )
    _patch_captures(
        monkeypatch,
        '[{"t":"Button","tx":"确定","l":"name::ok","ck":1}]',
    )
    payload = {
        "done": True,
        "steps": [
            {
                "keyword_id": "mobile_element_click",
                "params": {"locator": "xpath:://Button[@name='ghost']"},
            }
        ],
    }
    with pytest.raises(AuthoringError, match="未产生任何成功步骤"):
        run_session_authoring(
            AuthoringRequest(
                natural_language="点确定",
                platform="ios",
                mode="session",
            ),
            ctx=ExecutionContext(),
            chat=lambda _p: json.dumps(payload),
            executor=lambda step, ctx: None,
        )


def test_session_requires_ctx():
    with pytest.raises(AuthoringError, match="连接设备"):
        generate_traditional_case(
            AuthoringRequest(
                natural_language="打开演示应用并点击确定",
                platform="ios",
                mode="session",
                package_name="com.example.demo",
            ),
            ctx=None,
            save=False,
        )
