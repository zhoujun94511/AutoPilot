"""IDE 运行目标链路白盒：识别 web → 注入引擎/浏览器 → 报告 meta；AI 编写读工程平台。"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from autopilot.authoring.contract import AuthoringRequest
import autopilot.authoring.session_bootstrap as session_bootstrap_mod
from autopilot.engine.executor import RunResult, StepResult
from autopilot.engine.suite import SuiteResult
from autopilot.model.testcase import Step, StepSet, TestCase as CaseModel
from autopilot.ui.main_window.authoring import AuthoringMixin
from autopilot.ui.main_window.run import RunMixin


def _platform_from_project(project_dir: str) -> str:
    fn = getattr(session_bootstrap_mod, "_platform_from_project")
    return fn(project_dir)


prepare_authoring_session = session_bootstrap_mod.prepare_authoring_session


class _Host(RunMixin):
    pass


def _pass_result(name: str) -> RunResult:
    return RunResult(
        case_name=name,
        results=[StepResult(keyword_id="x", comment="", status="PASS")],
    )


def test_infer_web_from_nested_browser_keyword():
    h = _Host()
    tc = CaseModel(name="nested")
    tc.case.steps = [StepSet(name="g", children=[Step("browser_open")])]
    assert h._infer_web_platform(tc) is True
    assert h._case_target_platforms(tc, "android") == {"web"}


def test_target_platforms_aggregates_web_and_android():
    h = _Host()
    got = h._target_platforms(
        [
            CaseModel(name="w", platform="web"),
            CaseModel(name="a", platform="android"),
        ],
        "ios",
    )
    assert got == {"web", "android"}


def test_run_base_vars_web_injects_engine_without_device():
    import tempfile

    from tests._qt import get_qt_app
    from autopilot.model.testcase import TestCase
    from autopilot.ui.main_window import MainWindow

    get_qt_app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = ([], [])
        win._web_engine = "playwright"
        win._inspect_browser = "edge"
        base = win._run_base_vars(
            [TestCase(name="w", platform="web")],
            skip_device_pick=True,
        )
        win.close()
    assert base is not None
    assert base.get("__web_engine__") == "playwright"
    assert base.get("__web_browser__") == "edge"
    assert "__device_udid__" not in base


def test_run_base_vars_http_skips_mobile_backend():
    import tempfile

    from tests._qt import get_qt_app
    from autopilot.model.testcase import TestCase
    from autopilot.runtime import settings
    from autopilot.ui.main_window import MainWindow

    get_qt_app()
    with tempfile.TemporaryDirectory() as tmp:
        settings.set_project_platform(tmp, "http")
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = ([], [])
        win._ios_backend_mode = "wda"
        base = win._run_base_vars(
            [TestCase(name="api", platform="http")],
            skip_device_pick=True,
        )
        win.close()
    assert base is not None
    assert "__mobile_backend_mode__" not in base
    assert "__device_udid__" not in base
    assert base.get("__default_platform__") == "http"


def test_run_base_vars_default_web_sets_default_platform(tmp_path, monkeypatch):
    from tests._qt import get_qt_app
    from autopilot.model.testcase import TestCase
    from autopilot.runtime import settings
    from autopilot.ui.main_window import MainWindow

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    get_qt_app()
    proj = tmp_path / "proj"
    proj.mkdir()
    settings.set_project_platform(str(proj), "web")
    win = MainWindow(project_dir=str(proj), config_dir="")
    win._devices = ([], [])
    win._web_engine = "selenium"
    win._inspect_browser = "chrome"
    try:
        base = win._run_base_vars(
            [TestCase(name="generic")],
            skip_device_pick=True,
        )
    finally:
        win.close()
    assert base is not None
    assert base.get("__default_platform__") == "web"
    assert base.get("__web_engine__") == "selenium"
    assert base.get("__web_browser__") == "chrome"


def test_on_suite_done_report_meta_includes_web():
    from tests._qt import get_qt_app
    from autopilot.ui.main_window import MainWindow

    get_qt_app()
    captured: dict = {}

    def _fake_write(_suite, out, _generated_at="", report_meta=None):
        captured["meta"] = report_meta
        return out

    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._report_on_finish = True
        win._run_started_at = None
        win._run_case_paths = []
        win._fault_strategy = type("F", (), {"value": "continue"})()

        class _W:
            _base_vars = {"__default_platform__": "web"}

        win._worker = _W()
        with patch("autopilot.report.write_report", _fake_write), patch(
            "autopilot.report.write_result_json", lambda *_a, **_k: None
        ), patch(
            "autopilot.report.default_report_path",
            return_value=os.path.join(tmp, "r.html"),
        ):
            win._on_suite_done(SuiteResult(name="W", results=[_pass_result("c")]))
        win.close()
    meta = captured.get("meta")
    assert meta is not None
    assert "web" in (meta.platforms or [])


def test_platform_from_project_reads_settings(tmp_path, monkeypatch):
    from autopilot.runtime import settings

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    settings.set_project_platform(str(tmp_path), "web")
    assert _platform_from_project(str(tmp_path)) == "web"
    assert _platform_from_project("") == ""
    settings.set_project_platform(str(tmp_path), "generic")
    assert _platform_from_project(str(tmp_path)) == ""


def test_bootstrap_copies_project_dir_onto_request(tmp_path, monkeypatch):
    from autopilot.authoring.app_resolve import InstalledApp
    from autopilot.runtime import settings

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    settings.set_project_platform(str(tmp_path), "android")
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap._pick_udid",
        lambda platform, preferred="", **kw: "UDID-A",
    )
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda platform, **kw: InstalledApp("com.acme.demo", "Demo", platform),
    )
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="点击登录按钮",
            platform="",
            mode="session",
            project_dir=str(tmp_path),
        ),
        allow_nl_llm=False,
    )
    assert boot.request.platform == "android"
    assert boot.request.project_dir == str(tmp_path)


def test_authoring_mixin_passes_project_platform(tmp_path, monkeypatch):
    from autopilot.runtime import settings

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    settings.set_project_platform(str(tmp_path), "web")
    captured: dict = {}

    class FakeDlg:
        def __init__(self, *_a, **_kw):
            captured.update(_kw)

        @staticmethod
        def exec():
            return False

        @staticmethod
        def saved_path():
            return ""

    monkeypatch.setattr(
        "autopilot.ui.widgets.ai_authoring_dialog.AiAuthoringDialog",
        FakeDlg,
    )
    host = AuthoringMixin()
    host.project_dir = str(tmp_path)
    host.console = None
    host.project_tree = None
    host._inspect_ctx = None
    host.authoring_ai_assist()
    assert captured.get("default_platform") == "web"
    assert captured.get("project_dir") == str(tmp_path)


def test_dialog_generate_puts_project_dir_on_request(tmp_path, monkeypatch):
    from tests._qt import get_qt_app
    from autopilot.authoring.contract import AuthoringDraft, GeneratedStep
    from autopilot.authoring.nl_parse import NlHints
    from autopilot.authoring.pipeline import AuthoringResult
    from autopilot.keywords.context import ExecutionContext
    from autopilot.ui.widgets import ai_authoring_dialog as dlg_mod

    get_qt_app()
    monkeypatch.setattr(dlg_mod.QMessageBox, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr(dlg_mod.QMessageBox, "critical", lambda *_a, **_k: None)
    monkeypatch.setattr(dlg_mod.QMessageBox, "information", lambda *_a, **_k: None)
    dlg = dlg_mod.AiAuthoringDialog(
        None,
        project_dir=str(tmp_path),
        default_platform="web",
        chat_fn=lambda _p: "{}",
    )
    seen: list[AuthoringRequest] = []

    def fake_resolve(_nl, **_kw):
        return NlHints(platform="web", start_url="https://ex.test"), []

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

    def fake_gen(req, **_kw):
        return AuthoringResult(
            draft=AuthoringDraft(
                title="t",
                platform=req.platform,
                steps=[GeneratedStep(keyword_id="web_open", params={})],
                mode="session",
                goal_completed=True,
                session_verified=True,
            )
        )

    monkeypatch.setattr(dlg_mod, "resolve_nl_hints", fake_resolve)
    monkeypatch.setattr(dlg_mod, "prepare_authoring_session", fake_prepare)
    monkeypatch.setattr(dlg_mod, "generate_traditional_case", fake_gen)
    monkeypatch.setattr(dlg_mod, "release_authoring_session", lambda *_a, **_k: None)
    dlg.ed_nl.setPlainText("打开首页")
    dlg.ed_url.setText("https://ex.test")
    dlg._on_generate()
    assert seen
    assert seen[0].project_dir == str(tmp_path)
    assert seen[0].platform == "web"
