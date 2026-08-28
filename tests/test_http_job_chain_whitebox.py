"""HTTP Job 链路白盒：env 注入 → execute_job → session / api_env_use。

不走管理台 HTTP；载荷形状与 claim 的 JobOut 一致。不启真机 / 浏览器。
"""

from __future__ import annotations

import inspect

import pytest

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.http.env import (
    apply_job_http_env,
    api_env_use,
    resolve_http_env_profile,
)
from autopilot.keywords.registry import KeywordError
from autopilot.keywords.http.session import http_session_begin, http_session_end
from autopilot.mgmt.local_devices import probe_host_capabilities
from autopilot.runner.contract import JobOut, JobStatus
from autopilot.runner.execute import execute_job
from autopilot.runtime.job_platforms import apply_deviceless_run_target


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
        "id": fields.pop("id", "job-http-wb"),
        "name": fields.pop("name", "http-wb"),
        "status": "claimed",
        "project_dir": str(proj),
        "project_id": "p-mc",
        "platform": "http",
        "device_udids": [],
        "backend_mode": "auto",
        "web_engine": "selenium",
        "wda_bundle": "",
        "parallel": False,
        "parallel_workers": 0,
    }
    payload.update(fields)
    return JobOut.from_dict(payload)


def _run(job: JobOut, monkeypatch) -> dict:
    captured: dict = {}

    def fake_run(directory, **kwargs):
        captured["directory"] = directory
        captured.update(kwargs)
        return _FakeSuite()

    monkeypatch.setattr("autopilot.engine.run_project_directory", fake_run)
    monkeypatch.setattr("autopilot.report.write_report", lambda *a, **k: None)
    monkeypatch.setattr("autopilot.report.result_json.write_result_json", lambda *a, **k: None)
    result = execute_job(job)
    assert result.status == JobStatus.SUCCEEDED, result.error
    return captured


def _ctx(base_vars: dict) -> ExecutionContext:
    ctx = ExecutionContext()
    for key, value in dict(base_vars or {}).items():
        ctx.set_var(key, value)
    return ctx


def test_apply_job_http_env_missing_yaml_raises(tmp_path):
    with pytest.raises(KeywordError, match="api_env.yaml"):
        apply_job_http_env({}, project_dir=str(tmp_path), profile="staging")


def test_apply_job_http_env_unknown_profile_raises(tmp_path):
    (tmp_path / "api_env.yaml").write_text(
        "profiles:\n  dev:\n    base_url: http://127.0.0.1:9\n",
        encoding="utf-8",
    )
    with pytest.raises(KeywordError, match="no-such"):
        apply_job_http_env({}, project_dir=str(tmp_path), profile="no-such")


def test_apply_job_http_env_strict_false_skips_bad_profile(tmp_path):
    base = {"keep": 1}
    out = apply_job_http_env(
        base, project_dir=str(tmp_path), profile="staging", strict=False
    )
    assert out is base
    assert "__http_env_profile__" not in out
    resolved = resolve_http_env_profile(project_dir=str(tmp_path), profile="staging")
    assert resolved.error
    assert not resolved.ok


def test_execute_job_http_unknown_profile_fails(tmp_path, monkeypatch):
    (tmp_path / "suite").mkdir(exist_ok=True)
    (tmp_path / "suite" / "api_env.yaml").write_text(
        "profiles:\n  dev:\n    base_url: http://127.0.0.1:9\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("autopilot.engine.run_project_directory", lambda *a, **k: _FakeSuite())
    result = execute_job(_job(tmp_path, backend_mode="no-such-env"))
    assert result.status == JobStatus.FAILED
    assert "no-such-env" in (result.error or "")


def test_apply_job_http_env_auto_is_noop(tmp_path):
    base: dict = {"keep": 1}
    out = apply_job_http_env(base, project_dir=str(tmp_path), profile="auto")
    assert out is base
    assert "keep" in out
    assert "__http_env_profile__" not in out


def test_apply_job_http_env_loads_yaml_then_session_reads_base_url(tmp_path):
    (tmp_path / "api_env.yaml").write_text(
        "profiles:\n  staging:\n    base_url: https://api.example.test\n"
        "    vars:\n      api_token: t-stg\n",
        encoding="utf-8",
    )
    base: dict = {}
    apply_job_http_env(base, project_dir=str(tmp_path), profile="staging")
    assert base["__http_env_profile__"] == "staging"
    assert base["base_url"] == "https://api.example.test"
    assert base["api_token"] == "t-stg"

    ctx = _ctx(base)
    http_session_begin(ctx)
    assert ctx.http_session.base_url == "https://api.example.test"
    http_session_end(ctx)


def test_api_env_use_falls_back_to_job_injected_profile(tmp_path):
    (tmp_path / "api_env.yaml").write_text(
        "profiles:\n  staging:\n    base_url: http://stg.local\n    vars:\n      token: t-stg\n",
        encoding="utf-8",
    )
    ctx = ExecutionContext()
    ctx.set_var("__project_path__", str(tmp_path))
    ctx.set_var("__http_env_profile__", "staging")
    api_env_use(ctx)
    assert ctx.get_var("base_url") == "http://stg.local"
    assert ctx.get_var("token") == "t-stg"


def test_execute_job_http_injects_profile_into_keyword_ctx(tmp_path, monkeypatch):
    (tmp_path / "suite").mkdir(exist_ok=True)
    (tmp_path / "suite" / "api_env.yaml").write_text(
        "profiles:\n  dev:\n    base_url: http://127.0.0.1:9\n    vars:\n      api_token: t1\n",
        encoding="utf-8",
    )
    captured = _run(_job(tmp_path, backend_mode="dev"), monkeypatch)
    ctx = _ctx(captured["base_vars"] or {})
    assert ctx.get_var("__http_env_profile__") == "dev"
    assert ctx.get_var("base_url") == "http://127.0.0.1:9"
    http_session_begin(ctx)
    assert ctx.http_session.base_url == "http://127.0.0.1:9"
    http_session_end(ctx)
    assert ctx.get_var("api_token") == "t1"


def test_execute_job_http_auto_does_not_preinject_profile(tmp_path, monkeypatch):
    captured = _run(_job(tmp_path, backend_mode="auto"), monkeypatch)
    base = captured["base_vars"] or {}
    assert "__http_env_profile__" not in base
    assert "base_url" not in base
    assert "__web_engine__" not in base
    assert "__mobile_backend_mode__" not in base


def test_execute_job_http_branch_is_wired():
    src = inspect.getsource(execute_job)
    assert 'plat == "http"' in src
    assert "apply_job_http_env" in src
    assert "__http_env_profile__" in src


def test_runner_capabilities_always_include_http():
    caps, _backends = probe_host_capabilities()
    assert "http" in caps


def test_html_report_shows_http_profile():
    from autopilot.engine.suite import SuiteResult
    from autopilot.report import ReportMeta, render_report

    html = render_report(
        SuiteResult(name="s", results=[]),
        generated_at="t",
        meta=ReportMeta(
            suite_name="s",
            platforms=["http"],
            backend_mode="staging",
        ),
    )
    assert "staging" in html
    assert "运行环境" in html


def test_apply_deviceless_exported_for_job_create_consumers():
    from types import SimpleNamespace

    row = SimpleNamespace(
        platform="http",
        device_udids=["u1"],
        parallel=True,
        parallel_workers=2,
        wda_bundle="x",
        app_build_id="apk",
        web_engine="playwright",
        backend_mode="staging",
    )
    apply_deviceless_run_target(row)
    assert row.device_udids == []
    assert row.backend_mode == "staging"
