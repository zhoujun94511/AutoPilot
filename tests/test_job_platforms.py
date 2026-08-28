"""job_platforms 无设备目标剥离。"""

from __future__ import annotations

from types import SimpleNamespace

from autopilot.runtime.job_platforms import (
    BACKEND_MODE_MAX_LEN,
    DEVICELESS_PLATFORMS,
    JOB_PLATFORMS,
    apply_deviceless_run_target,
    apply_platform_side_effects,
    coerce_backend_mode,
    is_deviceless_platform,
    is_http_platform,
    normalize_stored_backend_mode,
)


def test_http_is_first_class_deviceless_platform():
    assert "http" in JOB_PLATFORMS
    assert "http" in DEVICELESS_PLATFORMS
    assert is_deviceless_platform("HTTP")
    assert is_http_platform("HTTP")
    assert not is_deviceless_platform("android")


def test_apply_deviceless_strips_mobile_keeps_http_profile():
    row = SimpleNamespace(
        platform="http",
        device_udids=["u1"],
        parallel=True,
        parallel_workers=4,
        wda_bundle="com.wda",
        app_build_id="apk-1",
        web_engine="playwright",
        backend_mode="staging",
    )
    apply_deviceless_run_target(row)
    assert row.device_udids == []
    assert row.parallel is False
    assert row.parallel_workers == 0
    assert row.wda_bundle == ""
    assert row.app_build_id is None
    assert row.web_engine == "selenium"
    assert row.backend_mode == "staging"


def test_apply_deviceless_web_keeps_playwright():
    row = SimpleNamespace(
        platform="web",
        device_udids=["u1"],
        parallel=True,
        parallel_workers=2,
        wda_bundle="x",
        app_build_id="apk-1",
        web_engine="playwright",
        backend_mode="chrome",
    )
    apply_deviceless_run_target(row)
    assert row.device_udids == []
    assert row.parallel is False
    assert row.app_build_id is None
    assert row.web_engine == "playwright"
    assert row.backend_mode == "chrome"


def test_normalize_stored_backend_mode_length():
    assert normalize_stored_backend_mode("  staging  ") == "staging"
    assert normalize_stored_backend_mode("") == "auto"
    long_ok = "p" * BACKEND_MODE_MAX_LEN
    assert normalize_stored_backend_mode(long_ok) == long_ok
    import pytest

    with pytest.raises(ValueError, match="最长"):
        normalize_stored_backend_mode("p" * (BACKEND_MODE_MAX_LEN + 1))


def test_coerce_backend_mode_http_resets_leftovers():
    assert coerce_backend_mode("http", "uia2") == "auto"
    assert coerce_backend_mode("http", "chrome") == "auto"
    assert coerce_backend_mode("http", "staging") == "staging"
    assert coerce_backend_mode("http", "my-qa") == "my-qa"
    assert coerce_backend_mode("http", "my-qa", extra_http_profiles=["dev"]) == "auto"
    assert coerce_backend_mode("web", "uia2") == "auto"
    assert coerce_backend_mode("web", "chrome") == "chrome"
    assert coerce_backend_mode("android", "edge") == "auto"
    assert coerce_backend_mode("android", "uia2") == "uia2"


def test_apply_deviceless_http_resets_mobile_backend():
    row = SimpleNamespace(
        platform="http",
        device_udids=["u1"],
        parallel=False,
        parallel_workers=0,
        wda_bundle="",
        app_build_id=None,
        web_engine="selenium",
        backend_mode="uia2",
    )
    apply_deviceless_run_target(row)
    assert row.backend_mode == "auto"


def test_apply_platform_side_effects_http_keeps_profile():
    form = {
        "device_udids": "U1",
        "parallel": True,
        "parallel_workers": 2,
        "wda_bundle": "com.wda",
        "backend_mode": "staging",
        "web_engine": "playwright",
        "app_build_id": "apk",
    }
    apply_platform_side_effects(form, "http")
    assert form["device_udids"] == ""
    assert form["backend_mode"] == "staging"
    assert form["web_engine"] == "selenium"


def test_apply_deviceless_skips_mobile():
    row = SimpleNamespace(
        platform="android",
        device_udids=["u1"],
        parallel=True,
        parallel_workers=3,
        wda_bundle="",
        app_build_id="apk-1",
        web_engine="selenium",
        backend_mode="uia2",
    )
    apply_deviceless_run_target(row)
    assert row.device_udids == ["u1"]
    assert row.parallel is True
    assert row.parallel_workers == 3
    assert row.app_build_id == "apk-1"
    assert row.backend_mode == "uia2"
