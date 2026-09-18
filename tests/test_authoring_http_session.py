"""HTTP / API 链路 3：观察 last_http、入口会话、Prompt 与对话框对齐。"""

from __future__ import annotations

import json

from autopilot.authoring import agent as agent_mod
from autopilot.authoring.agent import run_session_authoring
from autopilot.authoring.capture import capture_http_context, capture_ui_context
from autopilot.authoring.contract import AuthoringRequest, GeneratedStep
from autopilot.authoring.prompt import build_agent_turn_prompt, build_authoring_prompt
from autopilot.authoring.registry_catalog import build_keyword_catalog
from autopilot.authoring.session_bootstrap import prepare_authoring_session
from autopilot.keywords.context import ExecutionContext

_bootstrap_start_step = getattr(agent_mod, "_bootstrap_start_step")
_HTTP_IDS = {
    "http_session_begin",
    "http_get",
    "http_assert_status",
    "api_env_use",
}


def test_capture_http_empty_is_valid_observation():
    cap = capture_http_context(ExecutionContext())
    assert cap["platform"] == "http"
    payload = json.loads(cap["elements_text"])
    assert payload["kind"] == "http_observation"
    assert payload["session"]["begun"] is False
    assert payload["last_request"] is None
    assert cap["element_count"] == 0


def test_capture_ui_context_http_does_not_need_ui_tree():
    ctx = ExecutionContext()
    ctx.last_http = {
        "status": 200,
        "url": "https://api.example.test/health",
        "body": '{"ok":true}',
        "headers": {"content-type": "application/json"},
        "elapsed_ms": 11,
    }
    cap = capture_ui_context(ctx, "http")
    payload = json.loads(cap["elements_text"])
    assert payload["last_request"]["status"] == 200
    assert "ok" in payload["last_request"]["body"]


def test_bootstrap_start_step_http_opens_session():
    step = _bootstrap_start_step(
        AuthoringRequest(
            natural_language="检查健康检查",
            platform="http",
            start_url="https://api.example.test",
        ),
        "http",
    )
    assert step is not None
    assert step.keyword_id == "http_session_begin"
    assert step.params["base_url"] == "https://api.example.test"


def test_prepare_http_session_sets_base_url(tmp_path):
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="调用健康检查",
            platform="http",
            start_url="https://api.example.test",
            mode="session",
            project_dir=str(tmp_path),
        ),
        allow_nl_llm=False,
    )
    assert boot.request.platform == "http"
    assert boot.udid == ""
    assert boot.ctx.get_var("base_url") == "https://api.example.test"


def test_http_catalog_pins_core_and_blocks_delete():
    ids = {item["id"] for item in build_keyword_catalog("http", max_items=80)}
    expected = {
        "http_session_begin",
        "http_get",
        "http_post",
        "http_assert_status",
        "http_assert_body_contains",
        "api_env_use",
    }
    assert expected <= ids
    assert "http_delete" not in ids
    assert "mobile_element_click" not in ids


def test_http_prompts_use_response_observation_not_ui_tree():
    catalog = [{"id": "http_get", "params": [{"id": "url"}]}]
    obs = json.dumps(
        {
            "kind": "http_observation",
            "session": {"begun": True, "base_url": "https://api.example.test"},
            "last_request": None,
        },
        ensure_ascii=False,
    )
    plan = build_authoring_prompt(
        natural_language="GET /health 断言 200",
        platform="http",
        elements_text=obs,
        keyword_catalog=catalog,
        max_steps=8,
        start_url="https://api.example.test",
    )
    assert "接口观察" in plan
    assert "控件摘要" not in plan
    turn = build_agent_turn_prompt(
        natural_language="GET /health 断言 200",
        platform="http",
        elements_text=obs,
        keyword_catalog=catalog,
        history=[],
        start_url="https://api.example.test",
        remaining_steps=8,
    )
    assert "接口自动化" in turn
    assert "last_request" in turn
    assert "定位必须直接取自" not in turn
    assert "elementClick" not in turn


def test_http_session_authoring_observe_act_without_ui(monkeypatch):
    monkeypatch.setattr(
        agent_mod,
        "build_keyword_catalog",
        lambda _platform: [{"id": kid} for kid in sorted(_HTTP_IDS)],
    )
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda _platform: _HTTP_IDS,
    )
    locate_calls: list[int] = []

    def fake_locate(steps, *_args, **_kwargs):
        locate_calls.append(1)
        return steps, []

    monkeypatch.setattr(agent_mod, "resolve_planned_locators", fake_locate)
    ui_hits: list[str] = []

    def should_not_collect(*_a, **_k):
        ui_hits.append("ui")
        raise AssertionError("HTTP 编写不得采集 UI 树")

    monkeypatch.setattr(
        "autopilot.authoring.capture.collect_ui_elements",
        should_not_collect,
    )

    def execute(step: GeneratedStep, ctx: ExecutionContext) -> None:
        if step.keyword_id == "http_session_begin":
            ctx.http_session = type(
                "S",
                (),
                {"base_url": step.params.get("base_url", "")},
            )()
            return
        if step.keyword_id == "http_get":
            ctx.last_http = {
                "status": 200,
                "url": "https://api.example.test/health",
                "body": '{"ok":true}',
                "headers": {},
                "elapsed_ms": 9,
            }

    def chat(prompt: str) -> str:
        assert "控件摘要" not in prompt
        assert "http_observation" in prompt or "last_request" in prompt
        return json.dumps(
            {
                "done": True,
                "title": "健康检查",
                "steps": [
                    {
                        "keyword_id": "http_get",
                        "params": {"url": "/health"},
                        "action_role": "target",
                    },
                    {
                        "keyword_id": "http_assert_status",
                        "params": {"expected": "200"},
                        "action_role": "assert",
                    },
                ],
            }
        )

    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="GET /health 并断言 200",
            platform="http",
            start_url="https://api.example.test",
            mode="session",
        ),
        ctx=ExecutionContext(),
        chat=chat,
        executor=execute,
    )
    assert ui_hits == []
    assert locate_calls == []
    kids = [step.keyword_id for step in draft.steps]
    assert kids[0] == "http_session_begin"
    assert "http_get" in kids
    assert "http_assert_status" in kids
    assert draft.goal_completed is True
    assert draft.session_verified is True


def test_dialog_http_hides_try_and_relabels(tmp_path, monkeypatch):
    from tests._qt import get_qt_app
    from autopilot.ui.widgets import ai_authoring_dialog as dlg_mod

    get_qt_app()
    monkeypatch.setattr(dlg_mod.QMessageBox, "warning", lambda *a, **k: None)
    dlg = dlg_mod.AiAuthoringDialog(
        None, project_dir=str(tmp_path), default_platform="http"
    )
    assert dlg.cmb_platform.currentData() == "http"
    assert dlg.btn_gen.text() == "编写接口用例"
    assert dlg.btn_try.isHidden() is True
    assert dlg._lbl_url.text() == "接口 Base URL"
    assert "HTTP" in dlg.lbl_hint.text() or "接口" in dlg.lbl_hint.text()


def test_capture_settled_http_does_not_wait(monkeypatch):
    from autopilot.authoring.capture import capture_settled_ui_context

    monkeypatch.setattr(
        "autopilot.authoring.capture.time.sleep",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("HTTP 不应等待页面稳定")),
    )
    cap = capture_settled_ui_context(ExecutionContext(), "http")
    assert cap["_meta"]["settled"] is True
    assert cap["_meta"]["timed_out"] is False
    payload = json.loads(cap["elements_text"])
    assert payload["kind"] == "http_observation"


def test_capture_http_records_session_and_truncates_body():
    ctx = ExecutionContext()
    ctx.http_session = type("S", (), {"base_url": "https://api.example.test"})()
    ctx.last_http = {
        "status": 200,
        "url": "https://api.example.test/big",
        "body": "x" * 5000,
        "headers": {f"h{i}": "v" * 80 for i in range(20)},
        "elapsed_ms": 3,
    }
    cap = capture_http_context(ctx)
    payload = json.loads(cap["elements_text"])
    assert payload["session"]["begun"] is True
    assert payload["session"]["base_url"] == "https://api.example.test"
    assert payload["last_request"]["body"].endswith("…")
    assert len(payload["last_request"]["body"]) <= 4001
    assert len(payload["last_request"]["headers"]) <= 12
    assert cap["element_count"] == 1


def test_bootstrap_http_session_without_base_url():
    step = _bootstrap_start_step(
        AuthoringRequest(natural_language="调用接口", platform="http"),
        "http",
    )
    assert step is not None
    assert step.keyword_id == "http_session_begin"
    assert step.params == {}


def test_http_session_authoring_requires_ctx():
    from autopilot.authoring.contract import AuthoringError

    try:
        run_session_authoring(
            AuthoringRequest(natural_language="GET /health", platform="http"),
            ctx=None,
            chat=lambda _p: "{}",
        )
    except AuthoringError as exc:
        assert "接口编写缺少执行上下文" in str(exc)
    else:
        raise AssertionError("HTTP 无 ctx 应直接失败")


def test_http_session_authoring_without_assert_is_incomplete(monkeypatch):
    monkeypatch.setattr(
        agent_mod,
        "build_keyword_catalog",
        lambda _platform: [{"id": kid} for kid in sorted(_HTTP_IDS)],
    )
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda _platform: _HTTP_IDS,
    )
    monkeypatch.setattr(agent_mod, "resolve_planned_locators", lambda steps, *_a, **_k: (steps, []))

    def chat(_prompt: str) -> str:
        return json.dumps(
            {
                "done": True,
                "title": "健康检查",
                "steps": [
                    {
                        "keyword_id": "http_get",
                        "params": {"url": "/health"},
                        "action_role": "target",
                    }
                ],
            }
        )

    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="调用健康检查",
            platform="http",
            start_url="https://api.example.test",
            mode="session",
        ),
        ctx=ExecutionContext(),
        chat=chat,
        executor=lambda _step, _ctx: None,
    )
    assert "http_get" in [step.keyword_id for step in draft.steps]
    assert draft.goal_completed is False
    assert any("断言" in w for w in draft.warnings)
