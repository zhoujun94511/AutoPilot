"""通用目标 App 与内置诊断场景边界。"""

from __future__ import annotations

import pytest

from autopilot.diagnostics.scenarios import get_scenario, list_scenarios
from autopilot.mgmt.target_app import acquire_target_app


def test_generic_target_app_requires_explicit_package() -> None:
    with pytest.raises(ValueError, match="package_name 不能为空"):
        acquire_target_app()


def test_generic_target_app_has_no_implicit_scenario() -> None:
    target = acquire_target_app(
        package_name="com.example.app",
        app_label="Example",
        main_activity=".MainActivity",
        verify_installed=False,
    )
    assert target.package_name == "com.example.app"
    assert target.main_activity == ".MainActivity"
    assert target.source == "explicit"
    assert target.scenario == ""


def test_generic_android_target_can_verify_package(monkeypatch) -> None:
    monkeypatch.setattr(
        "autopilot.mgmt.target_app.android_package_exists",
        lambda _udid, _package: True,
    )
    monkeypatch.setattr(
        "autopilot.mgmt.target_app.android_package_version",
        lambda _udid, _package: "1.2.3",
    )
    target = acquire_target_app(
        udid="device-1",
        package_name="com.example.app",
    )
    assert target.version_name == "1.2.3"
    assert target.source == "explicit+adb"


def test_android_settings_is_registered_diagnostic_scenario() -> None:
    assert "android_settings" in list_scenarios()
    scenario = get_scenario("android_settings")
    target = scenario.acquire_target_app()
    assert target.package_name == "com.android.settings"
    assert target.scenario == "android_settings"
    assert target.source == "diagnostic:android_settings"
    assert scenario.resolve_assert_target() == "Wi-Fi"
    assert "Wi-Fi" in scenario.requirement()


def test_unknown_diagnostic_scenario_does_not_fallback() -> None:
    with pytest.raises(KeyError, match="unknown diagnostic scenario"):
        get_scenario("missing")
