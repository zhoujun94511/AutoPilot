"""链路 3 会话编写的门禁、会话复用与失败降级。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from autopilot.authoring.agent import run_session_authoring
from autopilot.authoring.contract import AuthoringDraft, AuthoringError, AuthoringRequest
from autopilot.authoring.gate import (
    assert_local_dry_run_passed,
    project_upload_blocked_reason,
    record_gate_result,
    unverified_drafts,
)
from autopilot.authoring.session_bootstrap import reusable_ctx
from autopilot.keywords.context import ExecutionContext


def _write_case(root: Path, name: str = "a.tc.yaml") -> Path:
    out = root / "authored"
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    path.write_text("type: testcase\n", encoding="utf-8")
    return path


def test_session_verified_draft_allows_upload(tmp_path: Path):
    path = _write_case(tmp_path)
    gate = assert_local_dry_run_passed(path, session_verified=True)
    assert gate.ok is True
    assert gate.allow_upload is True
    assert gate.verified_by == "session"


def test_plan_only_draft_needs_local_run(tmp_path: Path):
    path = _write_case(tmp_path)
    gate = assert_local_dry_run_passed(path, session_verified=False)
    assert gate.allow_upload is False
    assert gate.verified_by == ""


def test_gate_record_drives_project_upload_block(tmp_path: Path):
    path = _write_case(tmp_path)
    assert unverified_drafts(tmp_path) == ["a.tc.yaml"]
    assert "a.tc.yaml" in project_upload_blocked_reason(tmp_path)

    record_gate_result(path, assert_local_dry_run_passed(path, session_verified=True))
    assert unverified_drafts(tmp_path) == []
    assert project_upload_blocked_reason(tmp_path) == ""

    # 新增未验证草稿要重新拦
    _write_case(tmp_path, "b.tc.yaml")
    assert unverified_drafts(tmp_path) == ["b.tc.yaml"]


def test_draft_only_record_still_blocks_upload(tmp_path: Path):
    path = _write_case(tmp_path)
    record_gate_result(path, assert_local_dry_run_passed(path, draft_only=True))
    assert unverified_drafts(tmp_path) == ["a.tc.yaml"]


def _ios_ctx(udid: str = "UDID-1") -> ExecutionContext:
    ctx = ExecutionContext()
    ctx.set_var("__device_udid__", udid)
    ctx.set_var("__inspect_platform__", "iOS")
    return ctx


def test_reusable_ctx_matches_platform_and_device():
    ctx = _ios_ctx()
    assert reusable_ctx(ctx, "ios", udid="UDID-1") is True
    assert reusable_ctx(ctx, "ios", udid="UDID-2") is False
    assert reusable_ctx(ctx, "android", udid="UDID-1") is False
    assert reusable_ctx(None, "ios") is False


def test_prepare_session_reuses_inspector_ctx(monkeypatch):
    from autopilot.authoring import session_bootstrap as sb

    monkeypatch.setattr(sb, "_pick_udid", lambda platform, preferred="", **kw: "UDID-1")
    called: list[str] = []
    monkeypatch.setattr(
        sb,
        "_apply_mobile_session_vars",
        lambda *a, **kw: called.append("fresh"),
    )
    existing = _ios_ctx()
    boot = sb.prepare_authoring_session(
        AuthoringRequest(
            natural_language="打开Demo应用",
            platform="ios",
            mode="session",
            package_name="com.acme.demo",
        ),
        existing_ctx=existing,
    )
    assert boot.reused_ctx is True
    assert boot.ctx is existing
    assert called == []
    assert existing.get_var("app_package") == "com.acme.demo"


class _Dev:
    def __init__(self, udid: str, state: str = "ready") -> None:
        self.udid = udid
        self.state = state


def _patch_ios_devices(monkeypatch, devices: list[_Dev]) -> None:
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_ios_devices", lambda: devices)
    monkeypatch.setattr(
        "autopilot.mgmt.local_devices.list_android_devices", lambda: [])


def test_multi_device_asks_caller_and_honors_choice(monkeypatch):
    from autopilot.authoring import session_bootstrap as sb

    _patch_ios_devices(monkeypatch, [_Dev("UDID-1"), _Dev("UDID-2")])
    asked: list[tuple[str, list[str]]] = []

    def pick(platform: str, udids: list[str]) -> str:
        asked.append((platform, list(udids)))
        return "UDID-2"

    assert sb._pick_udid("ios", pick_device=pick) == "UDID-2"
    assert asked == [("ios", ["UDID-1", "UDID-2"])]


def test_multi_device_cancel_aborts(monkeypatch):
    from autopilot.authoring import session_bootstrap as sb

    _patch_ios_devices(monkeypatch, [_Dev("UDID-1"), _Dev("UDID-2")])
    try:
        sb._pick_udid("ios", pick_device=lambda platform, udids: "")
    except AuthoringError as exc:
        assert "已取消" in str(exc)
    else:
        raise AssertionError("取消选择时应中止而不是静默选第一台")


def test_multi_device_without_callback_takes_first(monkeypatch):
    """CLI / 无人值守没有回调，仍要能跑。"""
    from autopilot.authoring import session_bootstrap as sb

    _patch_ios_devices(monkeypatch, [_Dev("UDID-1"), _Dev("UDID-2")])
    assert sb._pick_udid("ios") == "UDID-1"


def test_no_ios_device_message_reports_tooling_error(monkeypatch):
    from autopilot.authoring import session_bootstrap as sb

    _patch_ios_devices(monkeypatch, [])
    monkeypatch.setattr(
        "autopilot.mobile.ios_devices.ios_tooling_error",
        lambda: "pymobiledevice3: No module named 'coloredlogs'",
    )
    try:
        sb._pick_udid("ios")
    except AuthoringError as exc:
        assert "coloredlogs" in str(exc)
    else:
        raise AssertionError("设备为空且工具链异常时应报出原因")


def test_unusable_device_message_reports_state_not_usb(monkeypatch):
    """已枚举到但不可用（如本机缺 iOS 后端）不能说成「请先插 USB」。"""
    from autopilot.authoring import session_bootstrap as sb

    dev = _Dev("UDID-1", state="error")
    dev.health_note = "no ios backend on this host"
    _patch_ios_devices(monkeypatch, [dev])
    with pytest.raises(AuthoringError) as caught:
        sb._pick_udid("ios")
    msg = str(caught.value)
    assert "UDID-1" in msg and "state=error" in msg
    assert "no ios backend on this host" in msg
    assert "请先用 USB 连接" not in msg


class _FakeChat:
    """按回合返回固定 JSON，模拟 LLM。"""

    def __init__(self, payloads: list[str]) -> None:
        self._payloads = payloads
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        idx = min(self.calls, len(self._payloads) - 1)
        self.calls += 1
        return self._payloads[idx]


def _turn(keyword_id: str, *, done: bool = False, text: str = "cat") -> str:
    return (
        '{"title": "搜索", "done": %s, "steps": [{"keyword_id": "%s", '
        '"params": {"locator": "id=q", "text": "%s"}, "comment": "输入"}]}'
        % ("true" if done else "false", keyword_id, text)
    )


def test_step_failure_degrades_to_replan(monkeypatch):
    from autopilot.authoring import agent as ag

    monkeypatch.setattr(
        ag,
        "build_keyword_catalog",
        lambda platform: [{"id": "mobile_element_text_input"}, {"id": "mobile_element_click"}],
    )
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda platform: {"mobile_element_text_input", "mobile_element_click"},
    )
    monkeypatch.setattr(ag, "capture_ui_context", lambda ctx, platform: {"elements_text": "[]"})

    attempts: list[str] = []

    def executor(step, _ctx):
        attempts.append(step.keyword_id)
        if step.keyword_id == "mobile_element_text_input":
            raise AuthoringError("控件未找到")

    chat = _FakeChat([_turn("mobile_element_text_input"), _turn("mobile_element_click", done=True)])
    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="在输入栏输入cat并搜索",
            platform="ios",
            mode="session",
            max_turns=4,
        ),
        ctx=ExecutionContext(),
        chat=chat,
        executor=executor,
    )
    assert attempts == ["mobile_element_text_input", "mobile_element_click"]
    assert [s.keyword_id for s in draft.steps] == ["mobile_element_click"]
    assert any("步骤失败已跳过" in w for w in draft.warnings)
    assert draft.session_verified is True


def test_consecutive_failures_stop_authoring(monkeypatch):
    from autopilot.authoring import agent as ag

    monkeypatch.setattr(ag, "build_keyword_catalog", lambda platform: [{"id": "mobile_element_click"}])
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda platform: {"mobile_element_click"},
    )
    monkeypatch.setattr(ag, "capture_ui_context", lambda ctx, platform: {"elements_text": "[]"})

    def executor(_step, _ctx):
        raise AuthoringError("控件未找到")

    chat = _FakeChat([_turn("mobile_element_click")])
    try:
        run_session_authoring(
            AuthoringRequest(
                natural_language="点搜索",
                platform="ios",
                mode="session",
                max_turns=10,
            ),
            ctx=ExecutionContext(),
            chat=chat,
            executor=executor,
        )
    except AuthoringError as exc:
        assert "未产生任何成功步骤" in str(exc)
    else:
        raise AssertionError("全失败时应抛出 AuthoringError")
    # 连续失败上限生效：不会把 max_turns 全部烧掉
    assert chat.calls == ag.MAX_CONSECUTIVE_FAILURES


def test_authoring_llm_calls_capped_per_case(monkeypatch):
    from autopilot.authoring import agent as ag

    monkeypatch.setenv("AUTOPILOT_AUTHORING_MAX_LLM_CALLS_PER_CASE", "2")
    monkeypatch.setenv("AUTOPILOT_AUTHORING_MAX_PROMPT_CHARS_PER_CASE", "500000")
    monkeypatch.setattr(
        ag, "build_keyword_catalog", lambda platform: [{"id": "mobile_element_click"}]
    )
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda platform: {"mobile_element_click"},
    )
    def capture(_ctx, _platform):
        return {"elements_text": "[]"}
    monkeypatch.setattr(ag, "capture_ui_context", capture)
    monkeypatch.setattr(ag, "capture_settled_ui_context", capture)

    chat = _FakeChat([_turn("mobile_element_click")])
    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="连续操作",
            platform="ios",
            mode="session",
            max_turns=8,
        ),
        ctx=ExecutionContext(),
        chat=chat,
        executor=lambda _step, _ctx: None,
    )
    assert chat.calls == 2
    assert any("AI 调用上限 2" in warning for warning in draft.warnings)


def test_llm_call_budget_follows_turn_budget():
    """护栏不能比回合预算还低，否则业务没写完就被截断。"""
    from autopilot.authoring import agent as ag

    assert ag._max_llm_calls(8) == 8 + ag.LLM_CALL_HEADROOM
    assert ag._max_llm_calls(20) == 20 + ag.LLM_CALL_HEADROOM
    assert ag._max_llm_calls(200) == ag.HARD_MAX_LLM_CALLS_PER_CASE


def test_turns_scale_with_step_budget():
    from autopilot.authoring.contract import HARD_MAX_TURNS, turns_for_steps

    # 40 步 / 每回合 4 步 = 10 回合，再留 2 回合重规划
    assert turns_for_steps(40, 8) == 12
    # 显式给更大的回合预算时不被折算值压低
    assert turns_for_steps(8, 20) == 20
    assert turns_for_steps(60, 999) == HARD_MAX_TURNS


def test_page_changing_step_ends_turn(monkeypatch):
    """借鉴 Midscene：点击等改页动作执行后停本回合，下一回合再观察。"""
    from autopilot.authoring import agent as ag

    ids = ["mobile_element_click"]
    els = (
        '[{"l":"name::a"},{"l":"name::b"},{"l":"name::c"},{"l":"name::d"}]'
    )
    monkeypatch.setattr(ag, "build_keyword_catalog", lambda platform: [{"id": i} for i in ids])
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids", lambda platform: set(ids)
    )
    cap = lambda ctx, platform, **kw: {"elements_text": els}  # noqa: E731
    monkeypatch.setattr(ag, "capture_ui_context", cap)
    monkeypatch.setattr(ag, "capture_settled_ui_context", cap)

    payloads = [
        {
            "done": False,
            "steps": [
                {"keyword_id": "mobile_element_click", "params": {"locator": "name::a"}},
                {"keyword_id": "mobile_element_click", "params": {"locator": "name::b"}},
            ],
        },
        {
            "done": True,
            "title": "两步点击",
            "steps": [
                {"keyword_id": "mobile_element_click", "params": {"locator": "name::c"}},
            ],
        },
    ]
    chat = _FakeChat([json.dumps(p) for p in payloads])
    draft = run_session_authoring(
        AuthoringRequest(natural_language="连续点击", platform="ios", mode="session"),
        ctx=ExecutionContext(),
        chat=chat,
        executor=lambda _step, _ctx: None,
    )
    assert chat.calls == 2
    assert [s.params["locator"] for s in draft.steps] == ["name::a", "name::c"]


def test_same_page_inputs_can_batch(monkeypatch):
    """同页不改页动作（输入）仍可一回合多步，避免无谓地一步一次调用。"""
    from autopilot.authoring import agent as ag

    ids = ["mobile_element_text_input"]
    els = '[{"l":"name::user"},{"l":"name::pass"}]'
    monkeypatch.setattr(ag, "build_keyword_catalog", lambda platform: [{"id": i} for i in ids])
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids", lambda platform: set(ids)
    )
    cap = lambda ctx, platform, **kw: {"elements_text": els}  # noqa: E731
    monkeypatch.setattr(ag, "capture_ui_context", cap)
    monkeypatch.setattr(ag, "capture_settled_ui_context", cap)

    payload = {
        "done": True,
        "title": "登录输入",
        "steps": [
            {
                "keyword_id": "mobile_element_text_input",
                "params": {"locator": "name::user", "text": "a"},
            },
            {
                "keyword_id": "mobile_element_text_input",
                "params": {"locator": "name::pass", "text": "b"},
            },
        ],
    }
    chat = _FakeChat([json.dumps(payload)])
    draft = run_session_authoring(
        AuthoringRequest(natural_language="填写账号密码", platform="ios", mode="session"),
        ctx=ExecutionContext(),
        chat=chat,
        executor=lambda _step, _ctx: None,
    )
    assert chat.calls == 1
    assert len(draft.steps) == 2


def _patch_agent_env(monkeypatch, ids: list[str], elements_text: str = "[]"):
    from autopilot.authoring import agent as ag

    monkeypatch.setattr(ag, "build_keyword_catalog", lambda platform: [{"id": i} for i in ids])
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids", lambda platform: set(ids)
    )

    def cap(_ctx, _platform, **_kw):
        return {"element_count": 1, "elements_text": elements_text}

    monkeypatch.setattr(ag, "capture_ui_context", cap)
    monkeypatch.setattr(ag, "capture_settled_ui_context", cap)
    return ag


def test_repeated_entry_step_is_skipped(monkeypatch):
    """实测故障：模型误判页面后反复重启 App，把用例塞满无效步骤还烧光回合。"""
    _patch_agent_env(monkeypatch, ["mobile_app_start", "mobile_element_click"])
    start = {
        "done": False,
        "steps": [
            {
                "keyword_id": "mobile_app_start",
                "params": {"type": "ios", "packageName": "com.demo", "activityName": ""},
            }
        ],
    }
    finish = {
        "done": True,
        "title": "搜索 cat",
        "steps": [{"keyword_id": "mobile_element_click", "params": {"locator": "name::go"}}],
    }
    chat = _FakeChat([json.dumps(start), json.dumps(finish)])
    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="打开应用并搜索",
            platform="ios",
            mode="session",
            package_name="com.demo",
        ),
        ctx=ExecutionContext(),
        chat=chat,
        executor=lambda _step, _ctx: None,
    )
    # 入口由 bootstrap 执行过一次，模型的重复启动被丢弃
    assert [s.keyword_id for s in draft.steps] == ["mobile_app_start", "mobile_element_click"]
    assert any("跳过重复入口" in w for w in draft.warnings)
    assert any("规划步骤均被过滤" in w for w in draft.warnings)
    assert not any("未给出可执行步骤" in w for w in draft.warnings)
    assert draft.goal_completed is True
    # 只有 done 的那一轮标题被采纳
    assert draft.title == "搜索 cat"


def test_observe_only_step_not_recorded(monkeypatch):
    ag = _patch_agent_env(monkeypatch, ["mobile_app_snapshot", "mobile_element_click"])
    payload = {
        "done": True,
        "title": "点搜索",
        "steps": [
            {"keyword_id": "mobile_app_snapshot", "params": {"fileName": "x"}},
            {"keyword_id": "mobile_element_click", "params": {"locator": "name::go"}},
        ],
    }
    draft = run_session_authoring(
        AuthoringRequest(natural_language="点搜索", platform="ios", mode="session"),
        ctx=ExecutionContext(),
        chat=_FakeChat([json.dumps(payload)]),
        executor=lambda _step, _ctx: None,
    )
    assert [s.keyword_id for s in draft.steps] == ["mobile_element_click"]
    assert any("截图步骤" in w for w in draft.warnings)
    assert ag.SNAPSHOT_KEYWORD_IDS


def test_snapshot_kept_when_user_asks(monkeypatch):
    ag = _patch_agent_env(monkeypatch, ["mobile_app_snapshot", "mobile_element_click"])
    payload = {
        "done": True,
        "title": "截图留证",
        "steps": [
            {"keyword_id": "mobile_app_snapshot", "params": {"fileName": "proof.png"}},
            {"keyword_id": "mobile_element_click", "params": {"locator": "name::go"}},
        ],
    }
    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="点搜索并截图留证",
            platform="ios",
            mode="session",
        ),
        ctx=ExecutionContext(),
        chat=_FakeChat([json.dumps(payload)]),
        executor=lambda _step, _ctx: None,
    )
    assert [s.keyword_id for s in draft.steps] == [
        "mobile_app_snapshot",
        "mobile_element_click",
    ]


def test_locator_outside_page_summary_rejected(monkeypatch):
    els = '[{"pl":"i","tx":"go","l":"name::go"}]'
    _patch_agent_env(monkeypatch, ["mobile_element_click"], elements_text=els)
    payload = {
        "done": True,
        "steps": [
            {"keyword_id": "mobile_element_click", "params": {"locator": "xpath:://Button[1]"}}
        ],
    }
    with pytest.raises(AuthoringError, match="未产生任何成功步骤"):
        run_session_authoring(
            AuthoringRequest(natural_language="点按钮", platform="ios", mode="session"),
            ctx=ExecutionContext(),
            chat=_FakeChat([json.dumps(payload)]),
            executor=lambda _step, _ctx: None,
        )


def test_cross_app_second_entry_allowed(monkeypatch):
    """跨包名入口应允许再次 mobile_app_start，不能一律幂等拦截。"""
    ag = _patch_agent_env(monkeypatch, ["mobile_app_start", "mobile_element_click"])
    payloads = [
        {
            "done": False,
            "steps": [
                {
                    "keyword_id": "mobile_app_start",
                    "params": {
                        "type": "ios",
                        "packageName": "com.other.app",
                        "activityName": "",
                    },
                }
            ],
        },
        {
            "done": True,
            "title": "跨应用",
            "steps": [
                {"keyword_id": "mobile_element_click", "params": {"locator": "name::go"}}
            ],
        },
    ]
    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="打开 A 再打开 B",
            platform="ios",
            mode="session",
            package_name="com.demo",
        ),
        ctx=ExecutionContext(),
        chat=_FakeChat([json.dumps(p) for p in payloads]),
        executor=lambda _step, _ctx: None,
    )
    kids = [s.keyword_id for s in draft.steps]
    assert kids.count("mobile_app_start") == 2
    assert draft.steps[0].params["packageName"] == "com.demo"
    assert draft.steps[1].params["packageName"] == "com.other.app"
    assert ag.ENTRY_KEYWORD_IDS


def test_turn_exhausted_draft_is_not_upload_ready(monkeypatch, tmp_path: Path):
    """每步都跑通但 AI 没确认达成需求时，不能默认放行上传。"""
    _patch_agent_env(monkeypatch, ["mobile_element_click"])
    payload = {
        "done": False,
        "steps": [{"keyword_id": "mobile_element_click", "params": {"locator": "name::go"}}],
    }
    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="点搜索",
            platform="ios",
            mode="session",
            max_steps=8,
            max_turns=2,
        ),
        ctx=ExecutionContext(),
        chat=_FakeChat([json.dumps(payload)]),
        executor=lambda _step, _ctx: None,
    )
    assert draft.session_verified is True
    assert draft.goal_completed is False

    path = _write_case(tmp_path)
    gate = assert_local_dry_run_passed(
        path,
        session_verified=draft.session_verified,
        goal_completed=draft.goal_completed,
    )
    assert gate.ok is True
    assert gate.allow_upload is False
    assert gate.verified_by == ""
    assert "goal_incomplete" in gate.details


def test_plan_only_draft_is_not_session_verified():
    draft = AuthoringDraft(title="t", platform="ios", steps=[])
    assert draft.session_verified is False


def test_release_owned_session_closes_drivers(monkeypatch):
    from autopilot.authoring import session_bootstrap as sb

    closed: list[str] = []

    class _Mobile:
        @staticmethod
        def close():
            closed.append("mobile")

    class _Web:
        @staticmethod
        def quit_all():
            closed.append("web")

    monkeypatch.setattr(
        "autopilot.keywords.mobile.driver.get_manager",
        lambda _ctx: _Mobile(),
    )
    monkeypatch.setattr(
        "autopilot.keywords.web.driver.get_manager",
        lambda _ctx: _Web(),
    )
    session_ctx = ExecutionContext()
    notes = sb.release_authoring_session(session_ctx, reused=False)
    assert closed == ["mobile", "web"]
    assert any("移动端" in n for n in notes)


def test_release_reused_session_keeps_drivers(monkeypatch):
    from autopilot.authoring import session_bootstrap as sb

    def boom(_ctx):
        raise AssertionError("复用会话不应关 driver")

    monkeypatch.setattr("autopilot.keywords.mobile.driver.get_manager", boom)
    monkeypatch.setattr("autopilot.keywords.web.driver.get_manager", boom)
    ctx = ExecutionContext()
    ctx.set_var("app_package", "com.demo.app")
    ctx.set_var("packageName", "com.demo.app")
    notes = sb.release_authoring_session(ctx, reused=True)
    assert ctx.get_var("app_package") == ""
    assert ctx.get_var("packageName") == ""
    assert any("复用会话" in n for n in notes)


def test_dialog_release_is_idempotent(monkeypatch):
    """关闭路径多次调用 release 不应重复关 driver（不拉起真实 Qt 事件循环）。"""
    from autopilot.ui.widgets import ai_authoring_dialog as dlg_mod

    calls: list[tuple] = []

    def fake_release(ctx, *, reused=False):
        calls.append((ctx, reused))

    monkeypatch.setattr(dlg_mod, "release_authoring_session", fake_release)

    # 只测回收状态机：绕过 UI 构造，直接塞属性
    class _Stub:
        _owned_ctx = None
        _reused_ctx = None
        _released = False

        def _release_session_resources(self):
            return dlg_mod.AiAuthoringDialog._release_session_resources(self)

    stub = cast(dlg_mod.AiAuthoringDialog, _Stub())
    owned = ExecutionContext()
    reused_ctx_obj = ExecutionContext()
    stub._owned_ctx = owned
    stub._reused_ctx = reused_ctx_obj
    stub._release_session_resources()
    stub._release_session_resources()
    assert calls == [(owned, False), (reused_ctx_obj, True)]
    assert stub._owned_ctx is None
    assert stub._reused_ctx is None
    assert stub._released is True
