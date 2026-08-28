"""B1-C：create-job 请求体构造。"""

from __future__ import annotations

import argparse

import pytest

from autopilot.mgmt.job_trigger import build_job_body


def _ns(**kwargs):
    defaults = dict(
        name="CI Suite",
        platform="android",
        project_id="",
        artifact_id="",
        app_build_id="",
        project_dir="",
        device_udids="",
        entry_paths="",
        parallel=False,
        parallel_workers=0,
        backend_mode="auto",
        web_engine="selenium",
        wda_bundle="",
        preferred_runner_id="",
        webhook_url="",
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_build_job_body_requires_source():
    with pytest.raises(ValueError, match="artifact-id|project-dir"):
        build_job_body(_ns())


def test_build_job_body_artifact_and_udids():
    body = build_job_body(
        _ns(
            artifact_id="art_1",
            platform="iOS",
            device_udids="u1, u2",
            entry_paths="a.tc.yaml,b.ts",
            preferred_runner_id="lab-1",
        )
    )
    assert body["artifact_id"] == "art_1"
    assert body["platform"] == "ios"
    assert body["device_udids"] == ["u1", "u2"]
    assert body["entry_paths"] == ["a.tc.yaml", "b.ts"]
    assert body["preferred_runner_id"] == "lab-1"


def test_build_job_body_project_dir_only():
    body = build_job_body(_ns(project_dir=r"D:\proj"))
    assert body["project_dir"] == r"D:\proj"
    assert body["artifact_id"] is None


def test_platform_help_lists_http():
    from pathlib import Path

    text = Path(__file__).resolve().parents[1].joinpath(
        "autopilot", "mgmt", "job_trigger.py"
    ).read_text(encoding="utf-8")
    assert "android|ios|web|http" in text
