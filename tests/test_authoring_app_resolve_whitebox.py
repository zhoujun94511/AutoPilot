"""应用解析 P0 白盒：rank/消歧/候选 → bootstrap/pick_app → agent 入口步 → 对话框接线。

覆盖链路（无真机）：
- ``rank_app_matches`` / ``_is_ambiguous_match`` 内部分支
- ``resolve_installed_app``：目录命中、显式包名、歧义、未命中候选
- ``_resolve_app_with_picker``：pick 成功 / 取消 / 未命中择一
- ``prepare_authoring_session``：正常解析、use_current_app、复用检视器、缺应用提示
- ``_bootstrap_start_step`` / ``run_session_authoring``：当前前台应用跳过启动步
- ``AiAuthoringDialog``：复选框与 pick_app 回调注入
"""

from __future__ import annotations

import json

import pytest

from autopilot.authoring import agent as agent_mod
from autopilot.authoring import app_resolve as ar_mod
from autopilot.authoring import session_bootstrap as sb_mod
from autopilot.authoring.app_resolve import (
    AppResolveAmbiguousError,
    AppResolveNotFoundError,
    InstalledApp,
    rank_app_matches,
    resolve_installed_app,
)
from autopilot.authoring.contract import (
    AuthoringError,
    AuthoringRequest,
    GeneratedStep,
)
from autopilot.authoring.session_bootstrap import prepare_authoring_session
from autopilot.keywords.context import ExecutionContext

_bootstrap_start_step = getattr(agent_mod, "_bootstrap_start_step")
_resolve_app_with_picker = getattr(sb_mod, "_resolve_app_with_picker")

_is_ambiguous_match = getattr(ar_mod, "_is_ambiguous_match")
_top_resolve_candidates = getattr(ar_mod, "_top_resolve_candidates")
_fill_android_labels = getattr(ar_mod, "_fill_android_labels")


# ---------------------------------------------------------------------------
# app_resolve 内部分支
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ranked,ambiguous",
    [
        ([(100, InstalledApp("a", "A", "ios")), (80, InstalledApp("b", "B", "ios"))], False),
        ([(80, InstalledApp("a", "A", "ios")), (80, InstalledApp("b", "B", "ios"))], True),
        ([(80, InstalledApp("a", "A", "ios")), (65, InstalledApp("b", "B", "ios"))], False),
        ([(80, InstalledApp("a", "A", "ios")), (50, InstalledApp("b", "B", "ios"))], False),
        ([(100, InstalledApp("a", "A", "ios"))], False),
    ],
)
def test_is_ambiguous_match_matrix(ranked, ambiguous):
    assert _is_ambiguous_match(ranked) is ambiguous


def test_rank_app_matches_orders_by_score_then_pkg_len():
    apps = [
        InstalledApp("com.long.package.name", "Demo Long", "ios"),
        InstalledApp("com.demo", "Demo", "ios"),
    ]
    ranked = rank_app_matches(apps, "demo", platform="ios")
    assert ranked[0][1].package_name == "com.demo"
    assert ranked[0][0] >= ranked[1][0]


def test_top_candidates_falls_back_to_alphabetical_when_no_scores():
    apps = [
        InstalledApp("com.z", "Zebra", "ios"),
        InstalledApp("com.a", "Alpha", "ios"),
    ]
    cands = _top_resolve_candidates(apps, [])
    assert [a.package_name for a in cands] == ["com.a", "com.z"]


def test_explicit_package_skips_fuzzy_and_ambiguity(monkeypatch):
    monkeypatch.setattr(
        ar_mod,
        "list_ios_installed_apps",
        lambda udid="": [
            InstalledApp("com.a.demo", "Demo App", "ios"),
            InstalledApp("com.a.demo.dev", "Demo Client", "ios"),
        ],
    )
    hit = resolve_installed_app(
        "ios", udid="U1", package_name="com.a.demo.dev", app_name="demo"
    )
    assert hit.package_name == "com.a.demo.dev"


def test_catalog_hit_bypasses_ambiguity(monkeypatch):
    monkeypatch.setattr(
        ar_mod,
        "list_ios_installed_apps",
        lambda udid="": [
            InstalledApp("com.apple.Preferences", "Settings", "ios"),
            InstalledApp("com.other.demo", "Demo App", "ios"),
            InstalledApp("com.other.demo2", "Demo Client", "ios"),
        ],
    )
    hit = resolve_installed_app("ios", udid="U1", app_name="设置")
    assert hit.package_name == "com.apple.Preferences"


# ---------------------------------------------------------------------------
# _resolve_app_with_picker
# ---------------------------------------------------------------------------


def test_resolve_app_with_picker_ambiguous_pick_success(monkeypatch):
    picked = InstalledApp("com.pick.me", "PickMe", "ios")

    def _raise_ambiguous(_platform, **_kw):
        raise AppResolveAmbiguousError(
            "ambiguous",
            candidates=[InstalledApp("com.a", "A", "ios"), picked],
        )

    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        _raise_ambiguous,
    )
    out = _resolve_app_with_picker(
        "ios",
        udid="U1",
        app_name="Demo",
        package_name="",
        pick_app=lambda _hint, cands: cands[1],
    )
    assert out.package_name == "com.pick.me"


def test_resolve_app_with_picker_ambiguous_cancel_raises(monkeypatch):
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda _platform, **_kw: (_ for _ in ()).throw(
            AppResolveAmbiguousError("ambiguous", candidates=[InstalledApp("com.a", "A", "ios")])
        ),
    )
    with pytest.raises(AuthoringError, match="多个候选"):
        _resolve_app_with_picker(
            "ios",
            udid="U1",
            app_name="Demo",
            package_name="",
            pick_app=lambda _hint, _cands: None,
        )


def test_resolve_app_with_picker_unattended_skips_pick(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_UNATTENDED", "1")
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda _platform, **_kw: (_ for _ in ()).throw(
            AppResolveAmbiguousError(
                "ambiguous",
                candidates=[InstalledApp("com.a", "A", "ios")],
            )
        ),
    )
    called: list[int] = []
    with pytest.raises(AuthoringError, match="多个候选"):
        _resolve_app_with_picker(
            "ios",
            udid="U1",
            app_name="Demo",
            package_name="",
            pick_app=lambda _hint, cands: called.append(1) or cands[0],
        )
    assert called == []


def test_resolve_app_with_picker_unattended_not_found_skips_pick(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_AUTHORING_UNATTENDED", "1")
    target = InstalledApp("com.fallback", "Fallback", "ios")
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda _platform, **_kw: (_ for _ in ()).throw(
            AppResolveNotFoundError("not found", candidates=[target])
        ),
    )
    called: list[int] = []
    with pytest.raises(AuthoringError, match="not found"):
        _resolve_app_with_picker(
            "ios",
            udid="U1",
            app_name="不存在",
            package_name="",
            pick_app=lambda _hint, cands: called.append(1) or cands[0],
        )
    assert called == []


def test_fill_android_labels_only_probes_unlabeled(monkeypatch):
    probed: list[str] = []

    def fake_label(pkg: str, serial: str) -> str:
        probed.append(f"{pkg}:{serial}")
        return f"Label-{pkg}"

    monkeypatch.setattr(ar_mod, "android_app_label", fake_label)
    apps = [
        InstalledApp("com.a", "Alpha", "android"),
        InstalledApp("com.b", "com.b", "android"),
        InstalledApp("com.c", "", "android"),
    ]
    assert _fill_android_labels(apps, udid="") == apps
    out = _fill_android_labels(apps, udid="S1")
    assert probed == ["com.b:S1", "com.c:S1"]
    assert out[0].app_label == "Alpha"
    assert out[1].app_label == "Label-com.b"
    assert out[2].app_label == "Label-com.c"


def test_android_not_found_llm_only_sees_filled_labels(monkeypatch):
    monkeypatch.setattr(
        ar_mod,
        "list_android_installed_packages",
        lambda udid="": [
            InstalledApp("com.demo.a", "", "android"),
            InstalledApp("com.demo.b", "com.demo.b", "android"),
        ],
    )
    monkeypatch.setattr(ar_mod, "_resolve_via_catalog_alias", lambda *_a, **_k: None)
    monkeypatch.setattr(ar_mod, "_enrich_android_labels", lambda apps, **_k: apps)
    monkeypatch.setattr(
        ar_mod,
        "_fill_android_labels",
        lambda apps, **_k: [
            InstalledApp("com.demo.a", "Alpha", "android"),
            InstalledApp("com.demo.b", "Beta", "android"),
        ],
    )
    prompts: list[str] = []
    hit = resolve_installed_app(
        "android",
        udid="U1",
        app_name="Beta Client",
        chat=lambda prompt: prompts.append(prompt)
        or json.dumps({"package_name": "com.demo.b"}),
    )
    assert hit.package_name == "com.demo.b"
    assert prompts and "Alpha | com.demo.a" in prompts[0]
    assert "Beta | com.demo.b" in prompts[0]


def test_android_unlabeled_pool_does_not_call_llm(monkeypatch):
    monkeypatch.setattr(
        ar_mod,
        "list_android_installed_packages",
        lambda udid="": [
            InstalledApp("com.demo.a", "", "android"),
            InstalledApp("com.demo.b", "com.demo.b", "android"),
        ],
    )
    monkeypatch.setattr(ar_mod, "_resolve_via_catalog_alias", lambda *_a, **_k: None)
    monkeypatch.setattr(ar_mod, "_enrich_android_labels", lambda apps, **_k: apps)
    monkeypatch.setattr(ar_mod, "_fill_android_labels", lambda apps, **_k: apps)
    called: list[str] = []
    with pytest.raises(AppResolveNotFoundError):
        resolve_installed_app(
            "android",
            udid="U1",
            app_name="NoSuchAppQwerty",
            chat=lambda prompt: called.append(prompt)
            or json.dumps({"package_name": "com.demo.a"}),
        )
    assert called == []


def test_resolve_app_with_picker_not_found_pick_success(monkeypatch):
    target = InstalledApp("com.fallback", "Fallback", "ios")
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda _platform, **_kw: (_ for _ in ()).throw(
            AppResolveNotFoundError("not found", candidates=[target])
        ),
    )
    out = _resolve_app_with_picker(
        "ios",
        udid="U1",
        app_name="不存在",
        package_name="",
        pick_app=lambda _hint, cands: cands[0],
    )
    assert out.package_name == "com.fallback"


# ---------------------------------------------------------------------------
# prepare_authoring_session 链路
# ---------------------------------------------------------------------------


def _patch_udid(monkeypatch, udid: str = "UDID-1") -> None:
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap._pick_udid",
        lambda _platform, preferred="", **_kw: udid,
    )


def test_bootstrap_normal_resolve_sets_ctx_vars(monkeypatch):
    _patch_udid(monkeypatch)
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda platform, **kw: InstalledApp("com.acme.demo", "Demo", platform),
    )
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="打开Demo应用",
            platform="ios",
            mode="session",
            app_label="Demo",
        ),
        allow_nl_llm=False,
    )
    assert boot.request.package_name == "com.acme.demo"
    assert boot.ctx.get_var("app_package") == "com.acme.demo"
    assert boot.ctx.get_var("__device_udid__") == "UDID-1"
    assert boot.resolved_app is not None


def test_bootstrap_missing_app_hint_suggests_current_app(monkeypatch):
    _patch_udid(monkeypatch)
    with pytest.raises(AuthoringError, match="当前前台应用"):
        prepare_authoring_session(
            AuthoringRequest(
                natural_language="点击登录按钮",
                platform="ios",
                mode="session",
            ),
            allow_nl_llm=False,
        )


def test_bootstrap_use_current_app_reuses_inspector_ctx(monkeypatch):
    _patch_udid(monkeypatch, "DEV-1")
    ctx = ExecutionContext()
    ctx.set_var("__device_udid__", "DEV-1")
    ctx.set_var("__inspect_platform__", "iOS")
    ctx.set_var("app_package", "com.already.open")
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="在当前页点击 Wi-Fi",
            platform="ios",
            mode="session",
            use_current_app=True,
        ),
        existing_ctx=ctx,
        allow_nl_llm=False,
    )
    assert boot.reused_ctx is True
    assert boot.request.use_current_app is True
    assert boot.request.package_name == ""
    assert boot.ctx is ctx


def test_bootstrap_use_current_app_rejects_web():
    with pytest.raises(AuthoringError, match="Android / iOS"):
        prepare_authoring_session(
            AuthoringRequest(
                natural_language="x",
                platform="web",
                mode="session",
                use_current_app=True,
            ),
            allow_nl_llm=False,
        )


def test_bootstrap_not_found_pick_app_chain(monkeypatch):
    _patch_udid(monkeypatch)
    fallback = InstalledApp("com.user.picked", "Picked", "ios")

    def _not_found(_platform, **_kw):
        raise AppResolveNotFoundError("未找到", candidates=[fallback])

    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        _not_found,
    )
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="打开神秘应用",
            platform="ios",
            mode="session",
            app_label="神秘",
        ),
        pick_app=lambda _hint, cands: cands[0],
        allow_nl_llm=False,
    )
    assert boot.request.package_name == "com.user.picked"


# ---------------------------------------------------------------------------
# agent 入口步链路
# ---------------------------------------------------------------------------


def test_bootstrap_start_step_normal_mobile_still_emits_app_start():
    req = AuthoringRequest(
        natural_language="x",
        platform="ios",
        package_name="com.example.app",
        app_label="Example",
    )
    step = _bootstrap_start_step(req, "ios")
    assert step is not None
    assert step.keyword_id == "mobile_app_start"
    assert step.params["packageName"] == "com.example.app"


def test_session_authoring_no_mobile_app_start_when_use_current_app(monkeypatch):
    from autopilot.authoring import agent as ag_mod
    from autopilot.authoring.agent import run_session_authoring

    def fake_capture(_ctx, platform, **_k):
        return {
            "platform": platform,
            "elements_text": '[{"t":"Button","tx":"OK","l":"name::ok","ck":1}]',
            "element_count": 1,
            "elements": [],
            "screen": "390x844",
        }

    monkeypatch.setattr(ag_mod, "capture_ui_context", fake_capture)
    monkeypatch.setattr(ag_mod, "capture_settled_ui_context", fake_capture)
    monkeypatch.setattr(
        ag_mod,
        "build_keyword_catalog",
        lambda _p, **_k: [{"id": "mobile_element_click", "params": []}],
    )

    executed: list[str] = []

    def fake_exec(step: GeneratedStep, _ctx) -> None:
        executed.append(step.keyword_id)

    def fake_chat(_prompt: str) -> str:
        return json.dumps(
            {
                "title": "点 OK",
                "done": True,
                "steps": [
                    {
                        "keyword_id": "mobile_element_click",
                        "params": {"locator": "name::ok"},
                        "comment": "点 OK",
                    }
                ],
            },
            ensure_ascii=False,
        )

    draft = run_session_authoring(
        AuthoringRequest(
            natural_language="点击 OK",
            platform="ios",
            mode="session",
            use_current_app=True,
        ),
        ctx=ExecutionContext(),
        chat=fake_chat,
        executor=fake_exec,
    )
    assert "mobile_app_start" not in executed
    assert all(s.keyword_id != "mobile_app_start" for s in draft.steps)
    assert draft.steps[0].keyword_id == "mobile_element_click"


# ---------------------------------------------------------------------------
# 对话框接线
# ---------------------------------------------------------------------------


def test_dialog_use_current_app_passed_to_bootstrap(tmp_path, monkeypatch):
    from tests._qt import get_qt_app
    from autopilot.ui.widgets import ai_authoring_dialog as dlg_mod
    from autopilot.authoring.nl_parse import NlHints

    get_qt_app()
    monkeypatch.setattr(dlg_mod.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(dlg_mod.QMessageBox, "critical", lambda *a, **k: None)

    prepare_calls: list[AuthoringRequest] = []

    def fake_resolve(_nl, **_kw):
        return NlHints(platform="ios", app_name=""), []

    def fake_prepare(req, **_kw):
        prepare_calls.append(req)
        ctx = ExecutionContext()
        return type(
            "Boot",
            (),
            {
                "request": req,
                "ctx": ctx,
                "notes": ["使用当前前台应用（跳过启动与包名解析）"],
                "reused_ctx": True,
                "udid": "U1",
                "resolved_app": None,
            },
        )()

    def fake_gen(req, **_kw):
        from autopilot.authoring.contract import AuthoringDraft
        from autopilot.authoring.pipeline import AuthoringResult

        return AuthoringResult(
            draft=AuthoringDraft(
                title="t",
                platform=req.platform,
                steps=[],
                mode="session",
                goal_completed=True,
            )
        )

    monkeypatch.setattr(dlg_mod, "resolve_nl_hints", fake_resolve)
    monkeypatch.setattr(dlg_mod, "prepare_authoring_session", fake_prepare)
    monkeypatch.setattr(dlg_mod, "generate_traditional_case", fake_gen)
    monkeypatch.setattr(dlg_mod, "release_authoring_session", lambda *a, **k: None)

    dlg = dlg_mod.AiAuthoringDialog(
        None,
        project_dir=str(tmp_path),
        default_platform="ios",
        chat_fn=lambda _p: "{}",
    )
    dlg.chk_current_app.setChecked(True)
    dlg.ed_nl.setPlainText("在当前页面点击返回")
    dlg._on_generate()

    assert len(prepare_calls) == 1
    assert prepare_calls[0].use_current_app is True


def test_dialog_pick_app_wired_to_bootstrap(tmp_path, monkeypatch):
    from tests._qt import get_qt_app
    from autopilot.ui.widgets import ai_authoring_dialog as dlg_mod

    get_qt_app()
    monkeypatch.setattr(dlg_mod.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(dlg_mod.QMessageBox, "critical", lambda *a, **k: None)

    pick_app_seen: list[bool] = []

    def fake_prepare(req, **_kw):
        fn = _kw.get("pick_app")
        pick_app_seen.append(callable(fn) and getattr(fn, "__name__", "") == "_pick_app")
        ctx = ExecutionContext()
        return type(
            "Boot",
            (),
            {
                "request": req,
                "ctx": ctx,
                "notes": [],
                "reused_ctx": False,
                "udid": "U1",
                "resolved_app": None,
            },
        )()

    def fake_gen(req, **_kw):
        from autopilot.authoring.contract import AuthoringDraft
        from autopilot.authoring.pipeline import AuthoringResult

        return AuthoringResult(
            draft=AuthoringDraft(
                title="t",
                platform=req.platform,
                steps=[],
                mode="session",
                goal_completed=True,
            )
        )

    monkeypatch.setattr(dlg_mod, "prepare_authoring_session", fake_prepare)
    monkeypatch.setattr(dlg_mod, "generate_traditional_case", fake_gen)
    monkeypatch.setattr(dlg_mod, "release_authoring_session", lambda *a, **k: None)
    monkeypatch.setattr(
        dlg_mod,
        "resolve_nl_hints",
        lambda _nl, **_kw: (
            type(
                "H",
                (),
                {
                    "platform": "ios",
                    "app_name": "Demo",
                    "package_name": "",
                    "start_url": "",
                    "input_texts": (),
                },
            )(),
            [],
        ),
    )

    dlg = dlg_mod.AiAuthoringDialog(
        None,
        project_dir=str(tmp_path),
        default_platform="ios",
        chat_fn=lambda _p: "{}",
    )
    dlg.ed_nl.setPlainText("打开 Demo")
    dlg._on_generate()
    assert pick_app_seen == [True]
