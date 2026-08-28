"""IDE Runner execute_job 与管理台 Job JSON 契约：注入变量被关键字读取。

不走 HTTP；载荷形状与 Platform claim 响应一致（JobOut.from_dict）。
真机 / 浏览器不启动。
"""

from __future__ import annotations

import inspect

from autopilot.keywords.context import ExecutionContext
import autopilot.keywords.mobile.session as mobile_session_mod
from autopilot.keywords.web.browser import browser_open
from autopilot.keywords.web.driver import resolve_web_engine
from autopilot.runner.contract import DeviceInfo, JobOut, JobStatus
from autopilot.runner.execute import execute_job


def _device_for_platform(ctx, platform: str) -> str:
    fn = getattr(mobile_session_mod, "_device_for_platform")
    return fn(ctx, platform)


class _FakeSuite:
    name = "Suite"
    duration_ms = 12
    results: list = []

    @staticmethod
    def case_counts() -> dict:
        return {"passed": 1, "failed": 0, "total": 1}


def _job(tmp_path, **fields) -> JobOut:
    proj = tmp_path / "suite"
    proj.mkdir(exist_ok=True)
    (proj / "c1.tc.yaml").write_text("name: c1\nsteps: []\n", encoding="utf-8")
    payload = {
        "id": fields.pop("id", "job-1"),
        "name": fields.pop("name", "n"),
        "status": "claimed",
        "project_dir": str(proj),
        "project_id": "p-mc",
        "platform": "web",
        "device_udids": [],
        "backend_mode": "auto",
        "web_engine": "selenium",
        "wda_bundle": "",
        "parallel": False,
        "parallel_workers": 0,
    }
    payload.update(fields)
    return JobOut.from_dict(payload)


def _run(job: JobOut, monkeypatch, *, devices=None) -> dict:
    captured: dict = {}

    def fake_run(directory, **kwargs):
        captured["directory"] = directory
        captured.update(kwargs)
        return _FakeSuite()

    monkeypatch.setattr("autopilot.engine.run_project_directory", fake_run)
    monkeypatch.setattr("autopilot.report.write_report", lambda *a, **k: None)
    monkeypatch.setattr("autopilot.report.result_json.write_result_json", lambda *a, **k: None)
    if devices is not None:
        monkeypatch.setattr(
            "autopilot.runner.devices.list_local_devices",
            lambda: list(devices),
        )
    result = execute_job(job)
    assert result.status == JobStatus.SUCCEEDED, result.error
    return captured


def _ctx(base_vars: dict) -> ExecutionContext:
    ctx = ExecutionContext()
    for key, value in dict(base_vars or {}).items():
        ctx.set_var(key, value)
    return ctx


def test_ide_execute_web_job_injects_engine_and_browser(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOPILOT_WEB_ENGINE", raising=False)
    job = _job(
        tmp_path,
        platform="web",
        web_engine="playwright",
        backend_mode="firefox",
    )
    captured = _run(job, monkeypatch)
    base = captured["base_vars"] or {}
    ctx = _ctx(base)
    assert resolve_web_engine(ctx) == "playwright"
    assert str(ctx.get_var("__web_browser__") or "") == "firefox"
    assert "__web_browser__" in inspect.getsource(browser_open)
    assert captured.get("platform") == "web"


def test_ide_execute_android_job_injects_udid_and_backend(tmp_path, monkeypatch):
    udid = "and-ide"
    job = _job(
        tmp_path,
        id="job-and",
        platform="android",
        backend_mode="uia2",
        device_udids=[udid],
    )
    devices = [DeviceInfo(udid=udid, platform="android", state="ready", backends=["android-appium"])]
    captured = _run(job, monkeypatch, devices=devices)
    base = captured["base_vars"] or {}
    ctx = _ctx(base)
    assert _device_for_platform(ctx, "Android") == udid
    assert str(ctx.get_var("__mobile_backend_mode__") or "") == "uia2"
    assert "__web_engine__" not in base


def test_ide_execute_ios_job_passes_wda_bundle(tmp_path, monkeypatch):
    udid = "ios-ide"
    wda = "com.ide.wda"
    job = _job(
        tmp_path,
        id="job-ios",
        platform="ios",
        backend_mode="wda",
        wda_bundle=wda,
        device_udids=[udid],
    )
    devices = [DeviceInfo(udid=udid, platform="ios", state="ready", backends=["ios-wda"])]
    captured = _run(job, monkeypatch, devices=devices)
    base = captured["base_vars"] or {}
    ctx = _ctx(base)
    assert _device_for_platform(ctx, "iOS") == udid
    assert captured.get("wda_bundle") == wda
    assert str(ctx.get_var("__mobile_backend_mode__") or "") == "wda"


def test_ide_execute_http_job_injects_env_profile(tmp_path, monkeypatch):
    (tmp_path / "suite").mkdir(exist_ok=True)
    (tmp_path / "suite" / "api_env.yaml").write_text(
        "profiles:\n  dev:\n    base_url: http://127.0.0.1:9\n    vars:\n      api_token: t1\n",
        encoding="utf-8",
    )
    job = _job(tmp_path, id="job-http", platform="http", backend_mode="dev")
    captured = _run(job, monkeypatch)
    base = captured["base_vars"] or {}
    ctx = _ctx(base)
    assert ctx.get_var("__http_env_profile__") == "dev"
    assert ctx.get_var("base_url") == "http://127.0.0.1:9"
    from autopilot.keywords.http.session import http_session_begin, http_session_end

    http_session_begin(ctx)
    assert ctx.http_session.base_url == "http://127.0.0.1:9"
    http_session_end(ctx)
