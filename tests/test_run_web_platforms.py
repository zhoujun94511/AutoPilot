"""IDE 运行目标平台：识别 web，并注入引擎/浏览器。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from autopilot.model.testcase import Step, TestCase as CaseModel
from autopilot.ui.main_window.run import RunMixin


class _Host(RunMixin):
    pass


def test_case_target_platforms_explicit_web():
    h = _Host()
    assert h._case_target_platforms(CaseModel(name="w", platform="web"), "android") == {"web"}


def test_case_target_platforms_default_web():
    h = _Host()
    assert h._case_target_platforms(CaseModel(name="g", platform=""), "web") == {"web"}


def test_case_target_platforms_infers_web_keyword():
    h = _Host()
    tc = CaseModel(name="k")
    tc.case.steps = [Step("web_open")]
    assert h._case_target_platforms(tc, "android") == {"web"}


def test_case_target_platforms_mobile_still_wins_over_default_web():
    h = _Host()
    assert h._case_target_platforms(CaseModel(name="a", platform="android"), "web") == {
        "android"
    }


def test_case_target_platforms_infers_http_keyword():
    h = _Host()
    tc = CaseModel(name="api")
    tc.case.steps = [Step("http_get")]
    assert h._case_target_platforms(tc, "android") == {"http"}


def test_case_target_platforms_explicit_http():
    h = _Host()
    assert h._case_target_platforms(CaseModel(name="h", platform="http"), "web") == {"http"}


def test_report_meta_platform_filter_includes_web():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath(
        "autopilot", "ui", "main_window", "run.py"
    ).read_text(encoding="utf-8")
    assert 'in ("android", "ios", "web", "http")' in src
