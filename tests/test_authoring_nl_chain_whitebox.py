"""链路 3 白盒：NL 前置混合解析 → bootstrap 接线 → Agent / 对话框。

覆盖内部分支（非真机黑盒）：
- resolve 三层优先级与跳过/降级路径
- ``_hints_from_llm_dict`` / 截断 / 开关
- ``prepare_authoring_session(allow_nl_llm=…)`` 是否二次打 LLM
- Agent 优先使用 ``AuthoringRequest.input_texts``
- ``AiAuthoringDialog``：一次 resolve + bootstrap 禁二次 LLM + 槽位入 Request
"""

from __future__ import annotations

import json

import pytest

from autopilot.authoring.agent import run_session_authoring
from autopilot.authoring.app_resolve import InstalledApp
from autopilot.authoring.contract import (
    AuthoringDraft,
    AuthoringError,
    AuthoringRequest,
    GeneratedStep,
)
from autopilot.authoring import nl_bootstrap as nl_bootstrap_mod
from autopilot.authoring.nl_bootstrap import (
    MAX_NL_EXTRACT_CHARS,
    extract_nl_hints_via_llm,
    hints_sufficient,
    merge_nl_hints,
    resolve_nl_hints,
)

_hints_from_llm_dict = getattr(nl_bootstrap_mod, "_hints_from_llm_dict")
_nl_llm_enabled = getattr(nl_bootstrap_mod, "_nl_llm_enabled")
from autopilot.authoring.nl_parse import NlHints
from autopilot.authoring.pipeline import AuthoringResult
from autopilot.authoring.session_bootstrap import prepare_authoring_session
from autopilot.keywords.context import ExecutionContext


# ---------------------------------------------------------------------------
# nl_bootstrap 内部分支
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hints,ok",
    [
        (NlHints(platform="web"), False),
        (NlHints(platform="web", start_url="https://a.test"), True),
        (NlHints(platform="ios"), False),
        (NlHints(platform="ios", app_name="设置"), True),
        (NlHints(platform="android", package_name="com.x"), True),
        (NlHints(package_name="com.x"), True),
        (NlHints(app_name="Demo"), True),
        (NlHints(platform="http"), True),
        (NlHints(), False),
    ],
)
def test_hints_sufficient_matrix(hints: NlHints, ok: bool):
    assert hints_sufficient(hints) is ok


def test_merge_url_infers_web_platform():
    m = merge_nl_hints(NlHints(), NlHints(start_url="https://ex.com/a"))
    assert m.platform == "web"
    assert m.start_url == "https://ex.com/a"


def test_explicit_overrides_llm_and_regex(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    calls: list[str] = []

    def chat(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(
            {
                "platform": "android",
                "app_name": "LLM应用",
                "package_name": "com.llm",
                "start_url": "",
                "input_texts": ["from_llm"],
            }
        )

    # 显式槽位已够用 → 根本不进 LLM
    hints, notes = resolve_nl_hints(
        "打开设置并输入 x",
        platform="ios",
        package_name="com.form",
        chat=chat,
    )
    assert hints.package_name == "com.form"
    assert hints.platform == "ios"
    assert calls == []
    assert "nl:explicit" in notes


def test_allow_llm_false_never_calls_chat(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    calls: list[int] = []

    def chat(_p: str) -> str:
        calls.append(1)
        return "{}"

    hints, notes = resolve_nl_hints(
        "帮我弄一下那个含糊的演示场景",
        chat=chat,
        allow_llm=False,
    )
    assert calls == []
    assert "nl:regex" in notes
    assert isinstance(hints, NlHints)


def test_llm_prompt_is_bootstrap_only_not_steps(monkeypatch):
    """白盒：抽取 Prompt 禁止规划步骤，只含槽位 schema。"""
    seen: list[str] = []

    def chat(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps(
            {
                "platform": "ios",
                "app_name": "Demo",
                "package_name": "",
                "start_url": "",
                "input_texts": [],
            }
        )

    extract_nl_hints_via_llm("随便说点含糊的", chat=chat)
    assert len(seen) == 1
    p = seen[0]
    assert "启动前置槽位" in p
    assert "不要规划" in p or "不要规划点击" in p
    assert "input_texts" in p
    assert "mobile_element_click" not in p
    assert "http" in p
    assert "不要仅因为出现 http(s) 就判成 web" in p


def test_llm_nl_truncated_before_complete_json(monkeypatch):
    seen: list[str] = []

    def chat(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps(
            {
                "platform": "",
                "app_name": "",
                "package_name": "",
                "start_url": "",
                "input_texts": [],
            }
        )

    long_nl = "测" * (MAX_NL_EXTRACT_CHARS + 200)
    extract_nl_hints_via_llm(long_nl, chat=chat)
    assert "…" in seen[0]
    # 截断后进 Prompt 的用户需求不应原样带完
    assert long_nl not in seen[0]


def test_hints_from_llm_dict_branches():
    with pytest.raises(AuthoringError, match="非对象"):
        _hints_from_llm_dict([])  # type: ignore[arg-type]

    h = _hints_from_llm_dict(
        {
            "platform": "IOS",
            "app_name": "  Demo ",
            "package_name": "com.demo",
            "start_url": "",
            "input_texts": ["a", "a", "b", ""],
            "input_text": "legacy",
        }
    )
    assert h.platform == "ios"
    assert h.app_name == "Demo"
    assert h.input_texts == ("a", "b", "legacy") or h.input_texts[0] == "legacy"
    # legacy 插到前面
    assert "legacy" in h.input_texts
    assert h.input_texts.count("a") == 1

    h2 = _hints_from_llm_dict(
        {"platform": "windows", "start_url": "https://x.test", "input_texts": []}
    )
    assert h2.platform == "web"  # 页面 URL 推断；非法 platform 被清掉后再推断

    h3 = _hints_from_llm_dict(
        {
            "platform": "windows",
            "start_url": "https://api.example.test/v1/users",
            "input_texts": [],
        }
    )
    assert h3.platform == "http"


def test_nl_llm_enabled_env_and_login(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "off")
    assert _nl_llm_enabled() is False

    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    monkeypatch.setattr(
        "autopilot.authoring.nl_bootstrap.llm_mode", lambda: "platform"
    )
    monkeypatch.setattr(
        "autopilot.runtime.settings.mc_is_logged_in", lambda: False
    )
    assert _nl_llm_enabled() is False

    monkeypatch.setattr(
        "autopilot.runtime.settings.mc_is_logged_in", lambda: True
    )
    assert _nl_llm_enabled() is True

    monkeypatch.setattr(
        "autopilot.authoring.nl_bootstrap.llm_mode", lambda: "local"
    )
    monkeypatch.setattr(
        "autopilot.intent.config.vision_api_key", lambda: ""
    )
    assert _nl_llm_enabled() is False
    monkeypatch.setattr(
        "autopilot.intent.config.vision_api_key", lambda: "sk-test"
    )
    assert _nl_llm_enabled() is True


def test_generic_exception_also_falls_back(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    # 放行与否取决于本机登录/Key，测试里固定住，避免依赖运行环境
    monkeypatch.setattr(
        "autopilot.authoring.nl_bootstrap._nl_llm_enabled", lambda: True
    )

    def boom(_p: str) -> str:
        raise RuntimeError("network down")

    _, notes = resolve_nl_hints(
        "帮我弄一下那个含糊场景",
        chat=boom,
        allow_llm=True,
    )
    assert any("llm_fallback" in n and "network down" in n for n in notes)


# ---------------------------------------------------------------------------
# bootstrap 接线：避免二次 LLM / 写入 input_texts
# ---------------------------------------------------------------------------


def test_prepare_session_allow_nl_llm_false_skips_extract(monkeypatch):
    llm_calls: list[str] = []

    def chat(prompt: str) -> str:
        llm_calls.append(prompt)
        return json.dumps(
            {
                "platform": "ios",
                "app_name": "LLM",
                "package_name": "com.llm",
                "start_url": "",
                "input_texts": ["x"],
            }
        )

    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap._pick_udid",
        lambda platform, preferred="", **kw: "U1",
    )
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda platform, **kw: InstalledApp("com.form", "FormApp", platform),
    )

    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="帮我弄一下含糊的东西",
            platform="ios",
            package_name="com.form",
            mode="session",
            input_texts=("form_user",),
        ),
        chat=chat,
        allow_nl_llm=False,
    )
    assert llm_calls == []
    assert boot.request.package_name == "com.form"
    assert boot.request.input_texts == ("form_user",)


def test_prepare_session_llm_fills_when_ambiguous(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_NL_LLM", "1")
    monkeypatch.setattr(
        "autopilot.authoring.nl_bootstrap._nl_llm_enabled", lambda: True
    )
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap._pick_udid",
        lambda platform, preferred="", **kw: "U1",
    )
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda platform, **kw: InstalledApp(
            "com.weather", kw.get("app_name") or "天气", platform
        ),
    )

    def chat(_p: str) -> str:
        return json.dumps(
            {
                "platform": "android",
                "app_name": "天气助手",
                "package_name": "",
                "start_url": "",
                "input_texts": ["上海"],
            },
            ensure_ascii=False,
        )

    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="帮我在安卓那个看天气的软件里查一下上海",
            platform="",
            mode="session",
        ),
        chat=chat,
        allow_nl_llm=True,
    )
    assert boot.request.platform == "android"
    assert boot.request.app_label == "天气助手" or "天气" in boot.request.app_label
    assert boot.request.input_texts == ("上海",)
    assert any(n == "nl:llm" for n in boot.notes)


# ---------------------------------------------------------------------------
# Agent：input_texts 来自 Request，不被空正则覆盖
# ---------------------------------------------------------------------------


def test_agent_prefers_request_input_texts(monkeypatch):
    from autopilot.authoring import agent as ag

    ids = {"mobile_element_text_input"}
    els = '[{"t":"TextField","l":"name::q","ed":1}]'
    monkeypatch.setattr(
        ag, "build_keyword_catalog", lambda platform: [{"id": i} for i in ids]
    )
    monkeypatch.setattr(
        "autopilot.authoring.codegen.allowed_keyword_ids",
        lambda platform: set(ids),
    )

    def cap(_ctx, _platform, **_kw):
        return {"element_count": 1, "elements_text": els, "screen": "100x200"}

    monkeypatch.setattr(ag, "capture_ui_context", cap)
    monkeypatch.setattr(ag, "capture_settled_ui_context", cap)

    prompts: list[str] = []

    def chat(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "done": True,
                "title": "输入",
                "steps": [
                    {
                        "keyword_id": "mobile_element_text_input",
                        "params": {"locator": "name::q", "text": "from_req"},
                    }
                ],
            }
        )

    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="随便说点不含输入动作的话",
            platform="ios",
            mode="session",
            input_texts=("from_req", "second"),
        ),
        ctx=ExecutionContext(),
        chat=chat,
        executor=lambda step, ctx: None,
    )
    assert draft.steps
    assert any("from_req" in p and "second" in p for p in prompts)
    assert "需求中要输入的文本：from_req、second" in prompts[0]


# ---------------------------------------------------------------------------
# UI 对话框接线：一次 NL LLM + bootstrap 禁止二次 + 槽位入 Request
# ---------------------------------------------------------------------------


def _make_dialog(tmp_path, monkeypatch, *, platform_data="auto", mode="session"):
    from tests._qt import get_qt_app
    from autopilot.ui.widgets import ai_authoring_dialog as dlg_mod

    get_qt_app()
    # 离屏测不弹 MessageBox
    monkeypatch.setattr(dlg_mod.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(dlg_mod.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(dlg_mod.QMessageBox, "information", lambda *a, **k: None)

    dlg = dlg_mod.AiAuthoringDialog(
        None,
        project_dir=str(tmp_path),
        default_platform="auto",
        chat_fn=lambda _p: "{}",
    )
    idx = dlg.cmb_platform.findData(platform_data)
    assert idx >= 0
    dlg.cmb_platform.setCurrentIndex(idx)
    midx = dlg.cmb_mode.findData(mode)
    assert midx >= 0
    dlg.cmb_mode.setCurrentIndex(midx)
    return dlg, dlg_mod


def test_dialog_resolve_once_then_bootstrap_skips_llm(tmp_path, monkeypatch):
    """对话框先 resolve(allow_llm=True)，bootstrap 必须 allow_nl_llm=False。"""
    dlg, dlg_mod = _make_dialog(tmp_path, monkeypatch, platform_data="auto")

    resolve_calls: list[dict] = []
    prepare_calls: list[dict] = []
    gen_reqs: list[AuthoringRequest] = []

    def fake_resolve(nl, **kw):
        resolve_calls.append({"nl": nl, **kw})
        return (
            NlHints(
                platform="ios",
                app_name="设置",
                package_name="com.apple.Preferences",
                input_texts=("wifi",),
            ),
            ["nl:llm"],
        )

    def fake_prepare(req, **kw):
        prepare_calls.append({"req": req, **kw})
        assert kw.get("allow_nl_llm") is False
        ctx = ExecutionContext()
        return type(
            "Boot",
            (),
            {
                "request": req,
                "ctx": ctx,
                "notes": ["boot:ok"],
                "reused_ctx": False,
                "udid": "U1",
                "resolved_app": None,
            },
        )()

    def fake_gen(req, **_kw):
        gen_reqs.append(req)
        draft = AuthoringDraft(
            title="t",
            platform=req.platform,
            steps=[GeneratedStep(keyword_id="mobile_launch_app", params={})],
            mode="session",
            goal_completed=True,
            session_verified=True,
        )
        return AuthoringResult(draft=draft)

    monkeypatch.setattr(dlg_mod, "resolve_nl_hints", fake_resolve)
    monkeypatch.setattr(dlg_mod, "prepare_authoring_session", fake_prepare)
    monkeypatch.setattr(dlg_mod, "generate_traditional_case", fake_gen)
    monkeypatch.setattr(dlg_mod, "release_authoring_session", lambda *a, **k: None)

    dlg.ed_nl.setPlainText("打开设置并搜索 wifi")
    dlg._on_generate()

    assert len(resolve_calls) == 1
    assert resolve_calls[0]["allow_llm"] is True
    assert resolve_calls[0]["platform"] == ""  # auto → 交给 resolve
    assert len(prepare_calls) == 1
    assert prepare_calls[0]["allow_nl_llm"] is False
    assert len(gen_reqs) == 1
    assert gen_reqs[0].platform == "ios"
    assert gen_reqs[0].package_name == "com.apple.Preferences"
    assert gen_reqs[0].app_label == "设置"
    assert gen_reqs[0].input_texts == ("wifi",)
    assert dlg.btn_save.isEnabled()
    assert dlg._draft is not None
    assert dlg._owned_ctx is None  # 生成后已释放
    assert dlg._generating is False


def test_dialog_explicit_platform_overrides_hints(tmp_path, monkeypatch):
    dlg, dlg_mod = _make_dialog(tmp_path, monkeypatch, platform_data="android")

    def fake_resolve(_nl, **kw):
        assert kw.get("platform") == "android"
        return (
            NlHints(platform="ios", app_name="Prefs", package_name="com.x"),
            [],
        )

    seen: list[AuthoringRequest] = []

    def fake_prepare(req, **_kw):
        seen.append(req)
        return type(
            "Boot",
            (),
            {
                "request": req,
                "ctx": ExecutionContext(),
                "notes": [],
                "reused_ctx": False,
                "udid": "",
                "resolved_app": None,
            },
        )()

    monkeypatch.setattr(dlg_mod, "resolve_nl_hints", fake_resolve)
    monkeypatch.setattr(dlg_mod, "prepare_authoring_session", fake_prepare)
    monkeypatch.setattr(
        dlg_mod,
        "generate_traditional_case",
        lambda req, **kw: AuthoringResult(
            draft=AuthoringDraft(
                title="t",
                platform=req.platform,
                steps=[],
                mode="session",
                goal_completed=True,
            )
        ),
    )
    monkeypatch.setattr(dlg_mod, "release_authoring_session", lambda *a, **k: None)

    dlg.ed_nl.setPlainText("打开随便什么")
    dlg._on_generate()
    assert seen[0].platform == "android"  # 下拉框优先于 LLM 猜的 ios


def test_dialog_plan_only_skips_prepare(tmp_path, monkeypatch):
    dlg, dlg_mod = _make_dialog(tmp_path, monkeypatch, mode="plan_only")

    prepare_hits: list[int] = []

    def boom_prepare(*_a, **_k):
        prepare_hits.append(1)
        raise AssertionError("plan_only 不应 prepare session")

    monkeypatch.setattr(
        dlg_mod,
        "resolve_nl_hints",
        lambda nl, **kw: (
            NlHints(platform="web", start_url="https://ex.test"),
            [],
        ),
    )
    monkeypatch.setattr(dlg_mod, "prepare_authoring_session", boom_prepare)

    def fake_gen(req, **kw):
        assert kw.get("ctx") is None
        assert req.platform == "web"
        assert req.start_url == "https://ex.test"
        return AuthoringResult(
            draft=AuthoringDraft(
                title="t",
                platform="web",
                steps=[],
                mode="plan_only",
                goal_completed=False,
            )
        )

    monkeypatch.setattr(dlg_mod, "generate_traditional_case", fake_gen)

    dlg.ed_nl.setPlainText("打开 https://ex.test 随便看看")
    dlg._on_generate()
    assert prepare_hits == []
    assert dlg.ed_url.text() == "https://ex.test"


def test_user_facing_notes_drops_internal_markers():
    from autopilot.authoring.contract import debug_note, user_facing_notes

    notes = [
        "nl:llm",
        "nl:llm_fallback:network down",
        debug_note("Appium 预检：boom"),
        "设备：U1",
        "应用：设置",
    ]
    assert user_facing_notes(notes) == ["设备：U1", "应用：设置"]


def test_dialog_status_hides_internal_notes(tmp_path, monkeypatch):
    """状态行只给用户看设备/应用，不暴露解析分支与排查线索。"""
    dlg, dlg_mod = _make_dialog(tmp_path, monkeypatch)
    from autopilot.authoring.contract import debug_note

    monkeypatch.setattr(
        dlg_mod,
        "resolve_nl_hints",
        lambda nl, **kw: (NlHints(platform="ios", app_name="设置"), ["nl:llm"]),
    )
    monkeypatch.setattr(
        dlg_mod,
        "prepare_authoring_session",
        lambda req, **kw: type(
            "Boot",
            (),
            {
                "request": req,
                "ctx": ExecutionContext(),
                "notes": [
                    "设备：U1",
                    "应用：设置",
                    debug_note("Appium 预检：boom"),
                ],
                "reused_ctx": False,
                "udid": "U1",
                "resolved_app": None,
            },
        )(),
    )
    monkeypatch.setattr(
        dlg_mod,
        "generate_traditional_case",
        lambda req, **kw: AuthoringResult(
            draft=AuthoringDraft(
                title="t",
                platform=req.platform,
                steps=[GeneratedStep(keyword_id="mobile_launch_app", params={})],
                mode="session",
                goal_completed=True,
            )
        ),
    )
    monkeypatch.setattr(dlg_mod, "release_authoring_session", lambda *a, **k: None)

    shown: list[str] = []
    orig = dlg.lbl_status.setText
    monkeypatch.setattr(
        dlg.lbl_status, "setText", lambda t: (shown.append(t), orig(t))[1]
    )

    dlg.ed_nl.setPlainText("打开设置")
    dlg._on_generate()

    joined = "\n".join(shown)
    assert "nl:" not in joined
    assert "debug:" not in joined
    assert "Appium" not in joined
    assert any("设备：U1" in s for s in shown)


def test_dialog_hint_has_no_config_jargon(tmp_path, monkeypatch):
    """顶部说明不该向普通用户解释运行模式与环境变量。"""
    dlg, _ = _make_dialog(tmp_path, monkeypatch)
    from PyQt6.QtWidgets import QLabel

    texts = [w.text() for w in dlg.findChildren(QLabel)]
    joined = "\n".join(texts)
    for jargon in ("AP_AI_API_KEY", "platform 模式", "local 模式", ".env", "F5"):
        assert jargon not in joined


def test_dialog_reentry_guard(tmp_path, monkeypatch):
    dlg, dlg_mod = _make_dialog(tmp_path, monkeypatch)
    dlg._generating = True
    hits = []
    monkeypatch.setattr(
        dlg_mod, "resolve_nl_hints", lambda *a, **k: hits.append(1) or (NlHints(), [])
    )
    dlg.ed_nl.setPlainText("不应进入")
    dlg._on_generate()
    assert hits == []


def test_dialog_lists_http_and_accepts_default(tmp_path, monkeypatch):
    dlg, _ = _make_dialog(tmp_path, monkeypatch, platform_data="http")
    values = [dlg.cmb_platform.itemData(i) for i in range(dlg.cmb_platform.count())]
    assert "http" in values
    assert dlg.cmb_platform.currentData() == "http"


def test_dialog_default_platform_http_not_collapsed_to_auto(tmp_path, monkeypatch):
    from tests._qt import get_qt_app
    from autopilot.ui.widgets import ai_authoring_dialog as dlg_mod

    get_qt_app()
    monkeypatch.setattr(dlg_mod.QMessageBox, "warning", lambda *a, **k: None)
    dlg = dlg_mod.AiAuthoringDialog(
        None, project_dir=str(tmp_path), default_platform="http"
    )
    assert dlg.cmb_platform.currentData() == "http"


def test_resolve_authoring_platform_url_rules():
    from autopilot.authoring.platform_resolve import resolve_authoring_platform

    assert (
        resolve_authoring_platform(
            start_url="https://example.com/login", project_platform="http"
        )
        == "http"
    )
    assert (
        resolve_authoring_platform(
            hints_platform="web",
            start_url="https://example.com/login",
            project_platform="http",
        )
        == "http"
    )
    assert resolve_authoring_platform(start_url="https://example.com/login") == "web"
    assert (
        resolve_authoring_platform(start_url="https://api.example.com/v1/users")
        == "http"
    )
    assert resolve_authoring_platform(explicit="http", start_url="https://a.com") == "http"


def test_compact_catalog_keeps_http_keywords():
    from autopilot.authoring.prompt import _compact_keyword_catalog

    raw = _compact_keyword_catalog(
        [
            {"id": "http_get", "params": [{"id": "url"}]},
            {"id": "web_browser_open", "params": [{"id": "url"}]},
            {"id": "excel_read", "params": []},
        ],
        platform="http",
    )
    assert "http_get" in raw
    assert "web_browser_open" not in raw
    assert "excel_read" not in raw
